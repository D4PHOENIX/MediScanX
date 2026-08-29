"""Proxy router for Dermatological (Skin-lesion) inference requests.

Routes uploaded dermatological imagery to the specialized downstream Skin
machine learning microservice for classification and risk assessment.

After receiving the ML result, the gateway intercepts the response to:
  1. Upload the raw image to Supabase Storage.
  2. Persist a structured ``scan_results`` row via ``ScanPersistenceService``.
  3. Augment the client-facing response with ``scan_id`` and ``image_url``.

# XAI handling — source of truth: gateway_backend/src/app/api/cxr_router.py
#
# The overlay-upload and xai_status logic below is a deliberate copy of the
# CXR router's equivalent block.  Both must be kept in sync whenever either
# is changed.  The only intentional deviations are:
#   - The ``metadata.xai`` JSONB key is NOT injected here (out of scope for skin).
#   - ``ai_diagnosis`` is sourced from ``predicted_class`` (string), not
#     ``predicted_diagnoses`` (list), which is the skin ML response shape.
"""

import base64
import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from httpx import HTTPStatusError, RequestError, AsyncClient, Response, Timeout

from app.core.config import gateway_config
from app.core.exceptions import ServiceUnavailableError
from app.core.security import get_current_user
from app.utils.attribution_utils import resolve_attribution
from app.utils.xai_utils import build_xai_authenticated_url
from app.services.scan_persistence_service import ScanPersistenceService
from app.services.storage_service import StorageService
from app.models.domain import ScanModality

logger = logging.getLogger(__name__)

router: APIRouter = APIRouter(prefix="/skin", tags=["Skin"])

_SKIN_URL: str = f"{gateway_config.skin_service_url}/predict"

# scan_type integer for Skin Lesion (matches scan_results schema)
_SCAN_TYPE_SKIN: int = 2


@router.post("/predict")
async def skin_predict(
    request: Request,
    file: UploadFile = File(...),
    top_k: int = Form(1),
    xai: bool = Form(True),
    patient_id: Optional[str] = Form(None),
    doctor_id: Optional[str] = Form(None),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Proxies an uploaded dermatological image to the inference microservice.

    Validates payload constraints before dispatching the visual data to the
    downstream predictive model for automated lesion risk classification.

    After inference, the gateway uploads the raw image to Supabase Storage and
    persists a structured row in ``scan_results`` before returning to the client.

    Args:
        request (Request): The incoming FastAPI request context containing the HTTP client.
        file (UploadFile): The binary file payload containing the dermatological image.
        top_k (int): The number of highest-probability diagnostic classes to return.
        doctor_id (Optional[str]): The doctor's UUID if captured during the session.
        user_id (str): The authenticated universal identifier of the calling user.

    Returns:
        Dict[str, Any]: The structured JSON response from the downstream Skin service,
            augmented with ``scan_id`` and ``image_url`` fields.

    Raises:
        HTTPException: Raises 413 if the payload exceeds operational size constraints.
        UpstreamServiceError: Raises 502 if the downstream service is unreachable
            or fails to process the request.
    """
    content: bytes = await file.read()

    if len(content) > gateway_config.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Uploaded file exceeds the maximum allowed size of "
                f"{gateway_config.max_upload_bytes // (1024 * 1024)} MiB."
            ),
        )

    headers = dict(request.headers)
    headers.pop("content-type", None)
    headers.pop("Content-Type", None)
    headers.pop("content-length", None)

    # Step 1: Proxy to Skin ML service
    try:
        client: AsyncClient = request.app.state.http_client
        resp: Response = await client.post(
            _SKIN_URL,
            headers=headers,
            files={
                "file": (
                    file.filename,
                    content,
                    file.content_type or "application/octet-stream",
                )
            },
            data={"top_k": top_k},
            params={"xai": "true" if xai else "false"},
            timeout=Timeout(30.0),
        )
        resp.raise_for_status()
    except (RequestError, HTTPStatusError) as exc:
        raise ServiceUnavailableError(
            context={"service": "skin", "url": _SKIN_URL, "detail": str(exc)}
        ) from exc

    ml_result: Dict[str, Any] = resp.json()

    # Steps 2-5: Persistence interceptor
    db_pool = request.app.state.db_pool

    final_user_id, final_doctor_id, _user_id_is_valid_uuid = resolve_attribution(
        user_id=user_id,
        patient_id=patient_id,
        doctor_id=doctor_id,
        service_name="Skin"
    )

    if db_pool and _user_id_is_valid_uuid:
        scan_id: str = str(uuid.uuid4())

        # Drop the large base64 source image before persistence.
        ml_result.pop("original_img", None)

        # --- XAI overlay handling (mirrors cxr_router.py) ---
        xai_path: Optional[str] = None
        xai_status: str = "none"
        has_overlays = False
        upload_success_count = 0
        uploaded_overlay_paths: list[str] = []

        top_findings = ml_result.get("top_findings", [])
        for idx, finding in enumerate(top_findings):
            if "overlay_img" in finding:
                has_overlays = True
                b64_img = finding.pop("overlay_img")

                try:
                    if b64_img.startswith("data:image"):
                        b64_data = b64_img.split(",", 1)[-1]
                    else:
                        b64_data = b64_img

                    img_bytes = base64.b64decode(b64_data)
                    overlay_path = f"{final_user_id}/{scan_id}/overlay_{idx}.png"

                    _, stored_path = await StorageService.upload_scan_image(
                        supabase_client=request.app.state.supabase_client,
                        bucket=gateway_config.supabase_storage_bucket,
                        user_id=final_user_id,
                        scan_id=scan_id,
                        file_bytes=img_bytes,
                        content_type="image/png",
                        object_path=overlay_path,
                    )
                    finding["overlay_path"] = stored_path
                    upload_success_count += 1
                    uploaded_overlay_paths.append(stored_path)

                    # Capture the top finding's overlay path for the canonical column.
                    if xai_path is None:
                        xai_path = stored_path
                except Exception as exc:
                    logger.warning("Skin overlay upload failed for finding %s: %s", idx, exc)

        if has_overlays:
            if upload_success_count > 0:
                xai_status = "generated"
            else:
                xai_status = "failed"
        else:
            xai_status = "none"
        # --- end XAI overlay handling ---

        # Step 2: Upload raw scan image to Supabase Storage
        image_url: str = ""
        storage_path: Optional[str] = None
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
            logger.error("Storage upload failed: %s", exc)
            if uploaded_overlay_paths:
                try:
                    await StorageService.delete_scan_objects(
                        supabase_client=request.app.state.supabase_client,
                        bucket=gateway_config.supabase_storage_bucket,
                        user_id=final_user_id,
                        object_paths=uploaded_overlay_paths,
                    )
                except Exception as cleanup_exc:
                    logger.warning("Orphaned overlay objects remaining after raw upload failure: %s (cleanup error: %s)", uploaded_overlay_paths, cleanup_exc)
            raise HTTPException(status_code=503, detail="Raw image upload failed.") from exc

        # Step 3: Derive severity from confidence
        top_findings = ml_result.get("top_findings", [])
        confidence: float = float(top_findings[0].get("confidence", 0.0)) if top_findings else 0.0
        ai_diagnosis: str = str(ml_result.get("predicted_class", ""))
        scan_status: int = ScanPersistenceService.derive_scan_status(
            confidence, ai_diagnosis=ai_diagnosis, modality="skin"
        )

        # Step 4: Persist to scan_results
        try:
            await ScanPersistenceService.insert_scan_result(
                pool=db_pool,
                scan_id=scan_id,
                user_id=final_user_id,
                doctor_id=final_doctor_id,
                scan_type=_SCAN_TYPE_SKIN,
                scan_status=scan_status,
                image_url=image_url,
                ai_diagnosis=ai_diagnosis,
                confidence=confidence,
                findings=str(ml_result.get("findings", "")),
                metadata=ml_result,
                inference_source="cloud",
                storage_path=storage_path,
                modality=ScanModality.SKIN.value,
                xai_path=xai_path,
                xai_status=xai_status,
            )
        except Exception as exc:
            logger.error("Failed to persist skin scan result: %s", exc)

            if uploaded_overlay_paths:
                try:
                    await StorageService.delete_scan_objects(
                        supabase_client=request.app.state.supabase_client,
                        bucket=gateway_config.supabase_storage_bucket,
                        user_id=final_user_id,
                        object_paths=uploaded_overlay_paths,
                    )
                except Exception as cleanup_exc:
                    logger.warning(
                        "Orphaned skin overlay objects remaining after persistence failure: %s "
                        "(cleanup error: %s)",
                        uploaded_overlay_paths,
                        cleanup_exc,
                    )

            # The endpoint does not swallow the exception — re-raise so the caller
            # receives a 500 rather than a silent empty response.
            raise

        # Step 5: Augment response with persistence identifiers
        ml_result["scan_id"] = scan_id
        ml_result["image_url"] = image_url
        ml_result["explainability"] = {
            "status": xai_status,
            "url": build_xai_authenticated_url(xai_path),
            "modality": ScanModality.SKIN.value,
        }

    return ml_result
