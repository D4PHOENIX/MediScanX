"""History, trends, and deletion endpoints for longitudinal scan tracking."""

import logging
import uuid
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core.config import gateway_config
from app.core.security import get_current_user
from app.models.domain import ScanModality
from app.models.schemas import ExplainabilityInfo, HistoryResponse, HistoryScanItem, TrendResponse, TrendTransition, ClaimRequest, ClaimResponse  # noqa: F401
from app.services.scans_service import ScansService
from app.services.storage_service import StorageService
from app.utils.labels import _ABNORMAL_LABELS, _NORMAL_LABELS  # noqa: F401
from app.utils.validation_utils import parse_uuid
from app.utils.xai_utils import build_xai_authenticated_url  # noqa: F401

logger: logging.Logger = logging.getLogger(__name__)


router: APIRouter = APIRouter(prefix="", tags=["scans"])


def get_status(label: Optional[str], mod: str) -> str:
    """Resolve the clinical status of a label based on the definitive label set."""
    if not label:
        return "unknown"
    if label in _NORMAL_LABELS.get(mod, set()):
        return "normal"
    if label in _ABNORMAL_LABELS.get(mod, set()):
        return "abnormal"
    return "unknown"


@router.get(
    "/history",
    response_model=HistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Paginated scan history for the authenticated caller.",
)
async def get_history(
    request: Request,
    modality: Optional[str] = Query(None, description="Filter by modality"),
    limit: int = Query(20, ge=1, le=100, description="Max scans to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    user_id: str = Depends(get_current_user),
) -> HistoryResponse:
    """Retrieves the paginated scan history for the authenticated caller.

    Fetches a chronologically ordered list of previous scans and their respective
    diagnoses, confidences, and explainability statuses. Filters can be applied
    to restrict the history to a specific diagnostic modality.

    Args:
        request (Request): The incoming FastAPI request context containing the database pool.
        modality (Optional[str], optional): The specific diagnostic modality to filter by (e.g., 'cxr', 'skin'). Defaults to None.
        limit (int, optional): The maximum number of scan records to return. Defaults to 20.
        offset (int, optional): The pagination offset. Defaults to 0.
        user_id (str): The authenticated universal identifier of the calling user.

    Returns:
        HistoryResponse: A structured response containing the total count of matching scans and the paginated list of scan items.

    Raises:
        HTTPException: Raises 422 if an invalid modality is provided, or 503 if the database is unavailable.
    """
    if modality and modality not in [m.value for m in ScanModality]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid modality: {modality}",
        )

    db_pool: asyncpg.Pool | None = request.app.state.db_pool
    if not db_pool:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection pool unavailable.",
        )

    user_uuid = parse_uuid(user_id, 'subject claim')
    try:
        return await ScansService.get_history(db_pool, user_uuid, modality, limit, offset)
    except asyncpg.PostgresError as e:
        import logging

        logging.getLogger(__name__).error("Database failure in /history: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database query failed"
        ) from e


@router.get(
    "/trends",
    response_model=TrendResponse,
    status_code=status.HTTP_200_OK,
    summary="Diagnosis progression over time for the authenticated caller.",
)
async def get_trends(
    request: Request,
    modality: str = Query(..., description="Modality filter is required for trends"),
    limit: int = Query(50, ge=1, le=200, description="Max scans to return"),
    user_id: str = Depends(get_current_user),
) -> TrendResponse:
    """Calculates the diagnosis progression over time for the authenticated caller.

    Analyzes a chronological sequence of scans for a specific modality to determine
    clinical transitions (e.g., worsening, improving, unchanged, changed, indeterminate)
    between consecutive scans.

    Args:
        request (Request): The incoming FastAPI request context containing the database pool.
        modality (str): The specific diagnostic modality to calculate trends for.
        limit (int, optional): The maximum number of scan records to analyze. Defaults to 50.
        user_id (str): The authenticated universal identifier of the calling user.

    Returns:
        TrendResponse: A structured response containing the sequence of analyzed scans and the computed transitions between them.

    Raises:
        HTTPException: Raises 422 if an invalid modality is provided, or 503 if the database is unavailable.
    """
    if modality not in [m.value for m in ScanModality]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid modality: {modality}",
        )

    db_pool: asyncpg.Pool | None = request.app.state.db_pool
    if not db_pool:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection pool unavailable.",
        )

    user_uuid = parse_uuid(user_id, 'subject claim')
    try:
        return await ScansService.get_trends(db_pool, user_uuid, modality, limit)
    except asyncpg.PostgresError as e:
        import logging
        logging.getLogger(__name__).error("Database failure in /trends: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database query failed"
        ) from e

@router.post(
    "/claim",
    response_model=ClaimResponse,
    status_code=status.HTTP_200_OK,
    summary="Claim a clinical report via QR token.",
)
async def claim_report_endpoint(
    payload: ClaimRequest,
    request: Request,
    user_id: str = Depends(get_current_user),
) -> ClaimResponse:
    db_pool: asyncpg.Pool | None = request.app.state.db_pool
    if not db_pool:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection pool unavailable.",
        )

    supabase_client = request.app.state.supabase_client

    try:
        return await ScansService.claim_report(db_pool, supabase_client, payload.token, user_id)
    except asyncpg.PostgresError as e:
        import logging
        logging.getLogger(__name__).error("Database failure in /claim: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database query failed"
        ) from e


@router.get(
    "/triage",
    response_model=HistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Triage list of scans for patients the doctor has access to.",
)
async def get_triage_endpoint(
    request: Request,
    limit: int = Query(20, ge=1, le=100, description="Max scans to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    user_id: str = Depends(get_current_user),
) -> HistoryResponse:
    db_pool: asyncpg.Pool | None = request.app.state.db_pool
    if not db_pool:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection pool unavailable.",
        )

    try:
        return await ScansService.get_triage(db_pool, user_id, limit, offset)
    except asyncpg.PostgresError as e:
        import logging
        logging.getLogger(__name__).error("Database failure in /triage: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database query failed"
        ) from e


@router.delete(
    "/{scan_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a scan owned by the authenticated caller.",
)
async def delete_scan(
    scan_id: str,
    request: Request,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Delete a scan row and its associated storage objects.

    Ordering guarantee: ownership verification precedes storage removal, which
    precedes row deletion. An orphaned storage object with no row pointing at it
    is unreclaimable (nothing knows it exists). A row pointing at missing objects
    is visible and diagnosable. Storage failure therefore leaves the row intact
    and returns 5xx so the caller can retry.

    Args:
        scan_id: Path parameter UUID of the scan to delete.
        request: FastAPI request context (carries db_pool and supabase_client).
        user_id: JWT-derived caller identity injected by get_current_user.

    Returns:
        dict: ``{"deleted": scan_id}`` on success.

    Raises:
        HTTPException 422: Malformed scan_id UUID (via parse_uuid).
        HTTPException 404: Scan absent or not owned by the caller. 404 is
            returned for both cases; 403 would confirm the scan_id exists.
        HTTPException 500: Storage removal failed; the row was NOT deleted.
        HTTPException 503: Database pool unavailable.
    """
    scan_uuid = parse_uuid(scan_id, "scan_id")
    user_uuid = parse_uuid(user_id, "user_id")

    db_pool: asyncpg.Pool | None = request.app.state.db_pool
    if not db_pool:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection pool unavailable.",
        )

    # Step 1 — Verify ownership before any destructive work.
    # An absent row and a row owned by another user both return 404.
    # Returning 403 for the latter would confirm that the scan_id exists.
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT storage_path, xai_path FROM scan_results "
            "WHERE scan_id = $1 AND user_id = $2",
            scan_uuid,
            user_uuid,
        )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scan not found.",
        )

    storage_path: Optional[str] = row["storage_path"]
    xai_path: Optional[str] = row["xai_path"]

    # Step 2 — Remove storage objects before deleting the row.
    # NULL paths are normal: storage_path is NULL when the raw upload failed
    # and cxr_inference_service swallowed the error (known production state).
    # xai_path is NULL when xai_status != 'generated'. Skip NULLs silently.
    # Both paths NULL means call storage zero times, then proceed to step 3.
    # If storage reports the object already absent, delete_scan_objects treats
    # that as success (it does not inspect remove()'s return value).
    object_paths = [p for p in [storage_path, xai_path] if p is not None]

    if object_paths:
        try:
            await StorageService.delete_scan_objects(
                supabase_client=request.app.state.supabase_client,
                bucket=gateway_config.supabase_storage_bucket,
                user_id=user_id,
                object_paths=object_paths,
            )
        except Exception as exc:
            logger.error(
                "Storage removal failed for scan_id=%s paths=%s: %s",
                scan_id,
                object_paths,
                exc,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Storage removal failed; scan row was not deleted.",
            ) from exc

    # Step 3 — Delete the row only after storage objects are confirmed gone.
    async with db_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM scan_results WHERE scan_id = $1 AND user_id = $2",
            scan_uuid,
            user_uuid,
        )

    return {"deleted": scan_id}
