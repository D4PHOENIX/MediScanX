"""Edge-inference sync router for offline-first TFLite scan uploads.

This router exposes a single ``POST /api/v1/sync/edge-inference`` endpoint that
acts as the rehydration entry-point for the Flutter mobile client's Local Outbox
Pattern.  When a device regains connectivity after running an on-device TFLite
scan in offline mode, it drains its ``pending_sync_scans`` SQLite queue by
POSTing each pending scan here.

Design contract:
  - The client supplies a **client-generated UUID** (``scan_id``) that was
    stored locally at inference time.  This UUID becomes the primary key in
    ``scan_results``, guaranteeing that retries never produce duplicate rows
    (``ON CONFLICT (scan_id) DO NOTHING``).
  - A ``200 Synced`` response means the row was written for the first time —
    the client MUST clear the local record and delete the cached image.
  - A ``409 Already Synced`` response means the scan already exists in Postgres
    (a safe idempotent outcome).  The client MUST also clear the local record.
  - Any ``5xx`` response means a transient server error — the client MUST keep
    the record and retry with exponential back-off (max 5 attempts).

Security:
  - JWT authentication via the standard ``get_current_user`` dependency.
  - The ``user_id`` form field is cross-validated against the authenticated JWT
    ``sub`` claim to prevent a rogue client from writing scans on behalf of
    another user.
"""

import json
import logging
from typing import Any, Dict, Optional, Union
import uuid as uuid_mod

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse

from app.core.config import gateway_config
from app.core.security import get_current_user
from app.utils.validation_utils import _validate_uuid
from app.models.schemas import ScanAlreadySyncedResponse, ScanSyncResponse
from app.services.scan_persistence_service import ScanPersistenceService
from app.services.storage_service import StorageService
from app.models.domain import ScanModality

logger: logging.Logger = logging.getLogger(__name__)

router: APIRouter = APIRouter(prefix="/sync", tags=["Edge Sync"])

# Accepted scan_type integers (mirrors the schema CHECK constraint)
_VALID_SCAN_TYPES: frozenset[int] = frozenset({0, 1, 2})

# Accepted scan_status integers
_VALID_SCAN_STATUSES: frozenset[int] = frozenset({0, 1, 2})



@router.post(
    "/edge-inference",
    response_model=Union[ScanSyncResponse, ScanAlreadySyncedResponse],
    status_code=status.HTTP_200_OK,
    summary="Sync an offline TFLite scan result to the cloud",
    description=(
        "Accepts a multipart payload containing the scan image and the TFLite "
        "inference metadata captured on-device.  Uploads the image to Supabase "
        "Storage, writes the scan result to `scan_results`, and returns the "
        "public image URL so the Flutter client can clear its local queue."
    ),
)
async def sync_edge_inference(
    request: Request,
    # Image file
    file: UploadFile = File(..., description="The scan image file (JPEG/PNG)."),
    # Required scan identifiers
    scan_id: str = Form(
        ...,
        description="Client-generated UUID.  Becomes the PK in scan_results.",
    ),
    patient_id: Optional[str] = Form(
        None,
        description="The patient's UUID. If provided, must match the authenticated JWT sub until RBAC is implemented.",
    ),
    scan_type: int = Form(
        ...,
        description="Modality: 0=ECG, 1=X-Ray, 2=Skin Lesion.",
    ),
    scan_status: int = Form(
        ...,
        description="Severity: 0=Normal, 1=Warning, 2=High Risk.",
    ),
    ai_diagnosis: str = Form(
        ...,
        description="Top-1 class label produced by the on-device TFLite model.",
    ),
    confidence: float = Form(
        ...,
        description="Top-1 confidence score in [0.0, 1.0].",
        ge=0.0,
        le=1.0,
    ),
    # Optional supplementary fields
    findings: str = Form(
        "",
        description="Free-text diagnostic findings from the TFLite output.",
    ),
    metadata: str = Form(
        "{}",
        description="Full TFLite inference JSON payload (serialised as a string).",
    ),
    modality: Optional[str] = Form(
        None,
        description="Modality of the scan: 'cxr', 'ecg', or 'skin'.",
    ),
    # Auth
    auth_user_id: str = Depends(get_current_user),
) -> JSONResponse:
    """Rehydrates an offline TFLite scan into the cloud ``scan_results`` table.

    This endpoint is designed exclusively for the Flutter mobile client's Local
    Outbox Pattern.  It must be called once per pending scan when the device
    regains internet connectivity.

    The endpoint is **fully idempotent**: submitting the same ``scan_id`` twice
    returns a 409 rather than creating a duplicate row.  The mobile client must
    treat both 200 and 409 as \"success\" conditions and clear the local queue entry.

    Args:
        request (Request): FastAPI request context carrying ``app.state``.
        file (UploadFile): The scan image binary.
        scan_id (str): Client-generated UUID for this scan.
        patient_id (Optional[str]): Patient UUID — cross-validated against the JWT.
        scan_type (int): Modality integer (0/1/2).
        scan_status (int): Severity integer (0/1/2).
        ai_diagnosis (str): TFLite top-1 class label.
        confidence (float): TFLite top-1 confidence in [0.0, 1.0].
        findings (str): Free-text findings; may be empty.
        metadata (str): Full TFLite JSON payload serialised as a string.
        modality (Optional[str]): Modality string ('cxr', 'ecg', 'skin').
        auth_user_id (str): JWT-derived user ID injected by ``get_current_user``.

    Returns:
        JSONResponse: 200 ``ScanSyncResponse`` on first insert,
            or 409 ``ScanAlreadySyncedResponse`` on duplicate.

    Raises:
        HTTPException 401: Missing or invalid JWT.
        HTTPException 403: ``patient_id`` does not match JWT ``sub``.
        HTTPException 413: File exceeds the upload size limit.
        HTTPException 422: Malformed UUID, invalid scan_type/scan_status, or
            unparseable metadata JSON.
        HTTPException 503: Database pool unavailable or storage upload failed.
    """
    #
    # 1. Input validation
    #
    form_data = await request.form()
    if "user_id" in form_data or "doctor_id" in form_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Client-supplied user_id and doctor_id form fields are rejected. Use patient_id for subject reference.",
        )

    _validate_uuid(scan_id, "scan_id")

    from app.utils.attribution_utils import resolve_attribution
    final_user_id, final_doctor_id, _is_valid_uuid = resolve_attribution(
        user_id=auth_user_id,
        patient_id=patient_id,
        doctor_id=None,
        service_name="Sync"
    )

    if scan_type not in _VALID_SCAN_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"scan_type must be one of {sorted(_VALID_SCAN_TYPES)}. Received: {scan_type}",
        )

    if scan_status not in _VALID_SCAN_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"scan_status must be one of {sorted(_VALID_SCAN_STATUSES)}. Received: {scan_status}",
        )

    try:
        metadata_dict: Dict[str, Any] = json.loads(metadata)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"metadata is not valid JSON: {exc}",
        ) from exc

    derived_modality = modality or metadata_dict.get("modality")
    if not derived_modality or derived_modality not in [m.value for m in ScanModality]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="modality could not be determined from the request.",
        )

    # Annotate the metadata with inference context for auditability
    metadata_dict.setdefault("inference_source", "edge")
    metadata_dict.setdefault("tflite_sync", True)

    #
    # 2. File size guard
    #
    content: bytes = await file.read()

    if len(content) > gateway_config.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Uploaded file exceeds the maximum allowed size of "
                f"{gateway_config.max_upload_bytes // (1024 * 1024)} MiB."
            ),
        )

    #
    # 3. Database pool guard
    #
    db_pool = request.app.state.db_pool
    if not db_pool:
        logger.error(
            "Edge sync attempted but DATABASE_URL is not configured. scan_id=%s",
            scan_id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database persistence is not configured on this server.",
        )

    #
    # Step 1 — duplicate pre-check.
    # SELECT scan_id, storage_path, user_id FROM scan_results WHERE scan_id = :scan_id
    #
    async with db_pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT scan_id, storage_path, user_id FROM scan_results WHERE scan_id = $1::uuid",
            scan_id,
        )

    if existing is not None:
        if str(existing["user_id"]) != final_user_id:
            # Foreign row: do not touch storage, do not insert, do not leak existing info.
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content={"error": True, "code": "scan_id_conflict", "detail": "scan_id belongs to another user."},
            )

        existing_storage_path = existing["storage_path"]
        if existing_storage_path:
            # Row exists with a non-null storage_path → already fully synced.
            # Do not touch storage. Return 409 with the existing path.
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "status": "already_synced",
                    "scan_id": scan_id,
                    "storage_path": existing_storage_path,
                },
            )
        # Row exists with null/empty storage_path → legacy partial.
        # Continue to upload; step 3 will UPDATE instead of INSERT.
        _is_partial_row = True
    else:
        _is_partial_row = False

    #
    # Step 2 — upload, then verify.
    # Upload the file; verify the returned object_path is non-empty.
    # StorageService.upload_scan_image returns (public_url, object_path).
    # On SDK failure it raises RuntimeError. A falsy object_path is treated
    # as a failed upload even if no exception was raised.
    #
    image_url: str
    storage_path: str

    try:
        image_url, storage_path = await StorageService.upload_scan_image(
            supabase_client=request.app.state.supabase_client,
            bucket=gateway_config.supabase_storage_bucket,
            user_id=final_user_id,
            scan_id=scan_id,
            file_bytes=content,
            content_type=file.content_type,
        )
    except RuntimeError as exc:
        logger.error(
            "Storage upload raised for edge scan_id=%s user_id=%s: %s",
            scan_id,
            final_user_id,
            exc,
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": True, "code": "storage_upload_failed", "detail": str(exc)},
        )

    if not storage_path:
        # Upload returned without raising but produced no usable object path.
        logger.error(
            "Storage upload returned falsy object_path for edge scan_id=%s user_id=%s",
            scan_id,
            final_user_id,
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": True, "code": "storage_upload_failed", "detail": "Storage returned no object path"},
        )

    # The storage service returns an absolute URL with /object/public/ which we need
    # to convert to /object/authenticated/ to match what the cloud write paths persist.
    authenticated_image_url = image_url.replace("/object/public/", "/object/authenticated/")

    #
    # Step 3 — insert (or update partial row).
    # INSERT ... ON CONFLICT (scan_id) DO NOTHING RETURNING scan_id.
    # storage_path and image_url come from the verified upload, never from client input.
    #
    if _is_partial_row:
        # Legacy partial row: update the storage fields where storage_path IS NULL.
        # This path has its own exception handler that must NOT issue a compensating
        # delete — the uploaded object belongs to the pre-existing row and deleting
        # it would reproduce B26 against a record that is already live.
        try:
            async with db_pool.acquire() as conn:
                updated = await conn.fetchrow(
                    """
                    UPDATE scan_results
                    SET storage_path = $1, image_url = $2
                    WHERE scan_id = $3::uuid AND user_id = $4::uuid AND storage_path IS NULL
                    RETURNING scan_id
                    """,
                    storage_path,
                    authenticated_image_url,
                    scan_id,
                    final_user_id,
                )
        except Exception as exc:
            logger.error(
                "Database update failed for partial edge row scan_id=%s user_id=%s: %s",
                scan_id,
                final_user_id,
                exc,
            )
            # Do NOT delete storage_path here — the object belongs to the pre-existing row.
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"error": True, "code": "sync_write_failed", "detail": str(exc)},
            )
        # Whether we updated or another concurrent request beat us, return 409.
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "status": "already_synced",
                "scan_id": scan_id,
                "storage_path": storage_path,
            },
        )

    try:
        was_inserted: bool = await ScanPersistenceService.insert_scan_result(
            pool=db_pool,
            scan_id=scan_id,
            user_id=final_user_id,
            doctor_id=final_doctor_id,
            scan_type=scan_type,
            scan_status=scan_status,
            image_url=authenticated_image_url,
            ai_diagnosis=ai_diagnosis,
            confidence=confidence,
            findings=findings,
            metadata=metadata_dict,
            inference_source="edge",
            storage_path=storage_path,
            modality=derived_modality,
        )
    except Exception as exc:
        logger.error(
            "Database insert failed for edge scan_id=%s user_id=%s: %s",
            scan_id,
            final_user_id,
            exc,
        )
        # Compensating delete: remove the object we just uploaded so it does not
        # become a permanent orphan.  A lost race (zero-rows / ON CONFLICT) is NOT
        # an exception and is not handled here — the winning row owns the object.
        try:
            await StorageService.delete_scan_objects(
                supabase_client=request.app.state.supabase_client,
                bucket=gateway_config.supabase_storage_bucket,
                user_id=final_user_id,
                object_paths=[storage_path],
            )
        except Exception as cleanup_exc:
            logger.error(
                "Compensating delete failed after insert failure — orphaned objects: %s (cleanup error: %s)",
                [storage_path],
                cleanup_exc,
            )

        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": True, "code": "sync_write_failed", "detail": str(exc)},
        )

    #
    # Step 3 outcomes
    #
    if was_inserted:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "synced",
                "scan_id": scan_id,
                "image_url": authenticated_image_url,
                "storage_path": storage_path,
            },
        )

    # ON CONFLICT fired — a concurrent request inserted the row first.
    # Re-read the conflicting row to check ownership.
    async with db_pool.acquire() as conn:
        conflicting_row = await conn.fetchrow(
            "SELECT user_id, storage_path FROM scan_results WHERE scan_id = $1::uuid",
            scan_id,
        )

    if conflicting_row and str(conflicting_row["user_id"]) != final_user_id:
        if conflicting_row["storage_path"] != storage_path:
            try:
                await StorageService.delete_scan_objects(
                    supabase_client=request.app.state.supabase_client,
                    bucket=gateway_config.supabase_storage_bucket,
                    user_id=final_user_id,
                    object_paths=[storage_path],
                )
            except Exception as cleanup_exc:
                logger.error(
                    "Compensating delete failed for foreign conflict orphaned object: %s",
                    cleanup_exc,
                )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": True, "code": "scan_id_conflict", "detail": "scan_id claimed by another user during sync."},
        )

    # The winning row belongs to the caller and points at the same deterministic object path.
    # Do NOT delete the object here.
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "status": "already_synced",
            "scan_id": scan_id,
            "storage_path": storage_path,
        },
    )
