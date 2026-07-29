"""Edge-inference sync router for offline-first TFLite scan uploads.

This router exposes ``POST /api/v1/sync/edge-inference``, the rehydration
entry-point for the Flutter client's Local Outbox Pattern. When a device
regains connectivity after running an on-device TFLite scan, it drains its
``pending_sync_scans`` SQLite queue by POSTing each pending scan here.

Design contract:
  - The client supplies a **client-generated UUID** (``scan_id``) stored
    locally at inference time. It becomes the primary key in ``scan_results``,
    so retries never produce duplicate rows (``ON CONFLICT (scan_id) DO NOTHING``).
  - **The client deletes its local copy only when the response body carries a
    non-null ``storage_path``.** The status code alone is not sufficient. The
    image on the device is frequently the only copy in existence, because the
    client holds a cache path rather than bytes.
  - ``200 synced`` — row written for the first time, image in storage. Carries
    ``storage_path``. Clear the local record and delete the cached image.
  - ``409 already_synced`` — the scan already exists, whether an idempotent
    retry or a completed partial. Carries ``storage_path``. Also a success.
  - ``422 scan_id_conflict`` — the ``scan_id`` belongs to another user's
    record. Permanent: keep the file, stop retrying, surface to the user.
  - ``413`` and other ``422`` responses — permanent payload errors. Same
    handling: keep, stop, surface.
  - ``503 storage_upload_failed`` / ``503 sync_write_failed``, and any other
    ``5xx`` — transient. Nothing was persisted. Keep the record and retry with
    exponential back-off (max 5 attempts).

Ordering guarantee:
  The image is uploaded and verified **before** the row is written. A row with
  a null ``storage_path`` is not a reachable outcome of this endpoint. If the
  insert fails after a successful upload the object is removed by a
  compensating delete — except where the uploaded path is the one a live row
  already points at.

Security:
  - JWT authentication via the standard ``get_current_user`` dependency.
  - ``user_id`` and ``doctor_id`` are **rejected outright** as form fields
    (422). Identity is derived solely from the JWT via ``resolve_attribution``;
    ``patient_id`` is the only client-supplied subject reference.
  - The duplicate pre-check and the partial-row repair are both scoped to the
    authenticated caller. They run on a pooled connection that does not
    traverse RLS, so the ``user_id`` predicate is the only thing standing
    between a client-supplied primary key and a cross-tenant read or write.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Union
import uuid as uuid_mod

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse

from app.core.config import gateway_config
from app.core.security import get_current_user
from app.utils.validation_utils import _validate_uuid
from app.models.schemas import ScanAlreadySyncedResponse, ScanSyncResponse
from app.services.edge_sync_service import EdgeSyncService, EdgeSyncOutcome
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
    validated = await _parse_and_validate_sync_request(
        request=request,
        scan_id=scan_id,
        patient_id=patient_id,
        auth_user_id=auth_user_id,
        scan_type=scan_type,
        scan_status=scan_status,
        metadata=metadata,
        modality=modality,
        file=file,
    )

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

    result = await EdgeSyncService.process_sync(
        db_pool=db_pool,
        supabase_client=request.app.state.supabase_client,
        scan_id=scan_id,
        final_user_id=validated.final_user_id,
        final_doctor_id=validated.final_doctor_id,
        scan_type=scan_type,
        scan_status=scan_status,
        ai_diagnosis=ai_diagnosis,
        confidence=confidence,
        findings=findings,
        metadata_dict=validated.metadata_dict,
        derived_modality=validated.derived_modality,
        content=validated.content,
        content_type=file.content_type,
    )

    if result.outcome == EdgeSyncOutcome.SYNCED:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "synced",
                "scan_id": result.scan_id,
                "image_url": result.image_url,
                "storage_path": result.storage_path,
            },
        )
    elif result.outcome == EdgeSyncOutcome.ALREADY_SYNCED:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "status": "already_synced",
                "scan_id": result.scan_id,
                "storage_path": result.storage_path,
            },
        )
    elif result.outcome == EdgeSyncOutcome.SCAN_ID_CONFLICT:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": True, "code": "scan_id_conflict", "detail": result.detail},
        )
    elif result.outcome == EdgeSyncOutcome.STORAGE_UPLOAD_FAILED:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": True, "code": "storage_upload_failed", "detail": result.detail},
        )
    elif result.outcome == EdgeSyncOutcome.WRITE_FAILED:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": True, "code": "sync_write_failed", "detail": result.detail},
        )
    else:
        logger.error(
            "Unhandled edge sync outcome %r for scan_id=%s", result.outcome, scan_id
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": True, "code": "unhandled_sync_outcome"},
        )

@dataclass
class ValidatedSyncRequest:
    final_user_id: str
    final_doctor_id: Optional[str]
    metadata_dict: Dict[str, Any]
    derived_modality: str
    content: bytes


async def _parse_and_validate_sync_request(
    request: Request,
    scan_id: str,
    patient_id: Optional[str],
    auth_user_id: str,
    scan_type: int,
    scan_status: int,
    metadata: str,
    modality: Optional[str],
    file: UploadFile,
) -> ValidatedSyncRequest:
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

    content: bytes = await file.read()
    if len(content) > gateway_config.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Uploaded file exceeds the maximum allowed size of "
                f"{gateway_config.max_upload_bytes // (1024 * 1024)} MiB."
            ),
        )

    return ValidatedSyncRequest(
        final_user_id=final_user_id,
        final_doctor_id=final_doctor_id,
        metadata_dict=metadata_dict,
        derived_modality=derived_modality,
        content=content,
    )
