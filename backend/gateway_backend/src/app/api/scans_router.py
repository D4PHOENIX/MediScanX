"""History and trends endpoints for longitudinal scan tracking."""

import uuid
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core.security import get_current_user
from app.models.domain import ScanModality
from app.models.schemas import HistoryResponse, HistoryScanItem, TrendResponse, TrendTransition
from app.utils.labels import _ABNORMAL_LABELS, _NORMAL_LABELS

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
):
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

    user_uuid = uuid.UUID(user_id)

    count_query = """
        SELECT COUNT(*)
        FROM scan_results
        WHERE user_id = $1 AND modality IS NOT NULL
    """
    count_args = [user_uuid]
    if modality:
        count_query += " AND modality = $2"
        count_args.append(modality)

    data_query = """
        SELECT scan_id, modality, ai_diagnosis, confidence, scan_status, scan_date, xai_status, storage_path
        FROM scan_results
        WHERE user_id = $1 AND modality IS NOT NULL
    """
    data_args = [user_uuid]
    if modality:
        data_query += " AND modality = $2"
        data_args.append(modality)

    # Append pagination and ordering
    data_query += f" ORDER BY scan_date DESC NULLS LAST LIMIT ${len(data_args) + 1} OFFSET ${len(data_args) + 2}"
    data_args.extend([limit, offset])

    try:
        async with db_pool.acquire() as conn:
            total_count = await conn.fetchval(count_query, *count_args)
            rows = await conn.fetch(data_query, *data_args)
    except asyncpg.PostgresError as e:
        import logging

        logging.getLogger(__name__).error("Database failure in /history: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database query failed"
        ) from e

    items = []
    for row in rows:
        items.append(
            HistoryScanItem(
                scan_id=str(row["scan_id"]),
                modality=row["modality"],
                ai_diagnosis=row["ai_diagnosis"] or "",
                confidence=float(row["confidence"]) if row["confidence"] is not None else None,
                scan_status=row["scan_status"],
                scan_date=row["scan_date"],
                xai_status=row["xai_status"] or "none",
                has_image=row["storage_path"] is not None,
            )
        )

    return HistoryResponse(total_count=total_count, items=items)


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
):
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

    user_uuid = uuid.UUID(user_id)

    query = """
        SELECT scan_id, modality, ai_diagnosis, confidence, scan_status, scan_date, xai_status, storage_path
        FROM (
            SELECT scan_id, modality, ai_diagnosis, confidence, scan_status, scan_date, xai_status, storage_path
            FROM scan_results
            WHERE user_id = $1 AND modality = $2 AND modality IS NOT NULL
            ORDER BY scan_date DESC NULLS LAST
            LIMIT $3
        ) sub
        ORDER BY scan_date ASC NULLS LAST
    """
    args = [user_uuid, modality, limit]

    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
    except asyncpg.PostgresError as e:
        import logging

        logging.getLogger(__name__).error("Database failure in /trends: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database query failed"
        ) from e

    scans = []
    for row in rows:
        scans.append(
            HistoryScanItem(
                scan_id=str(row["scan_id"]),
                modality=row["modality"],
                ai_diagnosis=row["ai_diagnosis"] or "",
                confidence=float(row["confidence"]) if row["confidence"] is not None else None,
                scan_status=row["scan_status"],
                scan_date=row["scan_date"],
                xai_status=row["xai_status"] or "none",
                has_image=row["storage_path"] is not None,
            )
        )

    transitions = []
    # Compute transitions between consecutive pairs
    for i in range(1, len(scans)):
        prev_scan = scans[i - 1]
        curr_scan = scans[i]

        days_between = None
        if curr_scan.scan_date and prev_scan.scan_date:
            days_between = (curr_scan.scan_date.date() - prev_scan.scan_date.date()).days

        confidence_delta = None
        if curr_scan.confidence is not None and prev_scan.confidence is not None:
            confidence_delta = round(curr_scan.confidence - prev_scan.confidence, 4)

        prev_status = get_status(prev_scan.ai_diagnosis, modality)
        curr_status = get_status(curr_scan.ai_diagnosis, modality)

        if prev_status == "unknown" or curr_status == "unknown":
            direction = "indeterminate"
        elif prev_status == "normal" and curr_status == "abnormal":
            direction = "worsening"
        elif prev_status == "abnormal" and curr_status == "normal":
            direction = "improving"
        elif prev_status == "abnormal" and curr_status == "abnormal":
            if prev_scan.ai_diagnosis == curr_scan.ai_diagnosis:
                direction = "unchanged"
            else:
                direction = "changed"
        else:  # normal -> normal
            direction = "unchanged"

        transitions.append(
            TrendTransition(
                from_diagnosis=prev_scan.ai_diagnosis,
                to_diagnosis=curr_scan.ai_diagnosis,
                days_between=days_between,
                confidence_delta=confidence_delta,
                direction=direction,
            )
        )

    return TrendResponse(scans=scans, transitions=transitions)
