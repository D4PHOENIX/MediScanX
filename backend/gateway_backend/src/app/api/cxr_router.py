"""Proxy router for Chest X-Ray (CXR) inference requests.

Routes uploaded chest radiograph images to the specialized downstream CXR
machine learning microservice, ensuring payload constraints and authorization
are rigorously enforced at the gateway boundary.

After receiving the ML result, the gateway intercepts the response to:
  1. Upload the raw image to Supabase Storage.
  2. Persist a structured ``scan_results`` row via ``ScanPersistenceService``.
  3. Augment the client-facing response with ``scan_id`` and ``image_url``.
"""

import logging
import uuid
import base64
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

router: APIRouter = APIRouter(prefix="/cxr", tags=["CXR"])

_CXR_URL: str = f"{gateway_config.cxr_service_url}/predict"

# scan_type integer for Chest X-Ray (matches scan_results schema)
_SCAN_TYPE_CXR: int = 1


@router.post("/predict")
async def cxr_predict(
    request: Request,
    file: UploadFile = File(...),
    top_k: int = Form(3),
    patient_id: Optional[str] = Form(None),
    doctor_id: Optional[str] = Form(None),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Proxies an uploaded chest radiograph to the CXR inference microservice.

    Validates the inbound payload size against configured thresholds before
    initiating a multipart transfer to the downstream machine learning engine
    for diagnostic classification.

    After inference, the gateway uploads the raw image to Supabase Storage and
    persists a structured row in ``scan_results`` before returning to the client.

    Args:
        request (Request): The incoming FastAPI request context containing the HTTP client.
        file (UploadFile): The binary file payload containing the chest radiograph.
        top_k (int): The number of highest-probability diagnostic classes to return.
        doctor_id (Optional[str]): The doctor's UUID if captured during the session.
        user_id (str): The authenticated universal identifier of the calling user.

    Returns:
        Dict[str, Any]: The structured JSON response from the downstream CXR service,
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

    # Step 1: Proxy to CXR ML service
    try:
        client: AsyncClient = request.app.state.http_client
        resp: Response = await client.post(
            _CXR_URL,
            headers=headers,
            files={
                "file": (
                    file.filename,
                    content,
                    file.content_type or "application/octet-stream",
                )
            },
            data={"top_k": top_k},
            timeout=Timeout(30.0),
        )
        resp.raise_for_status()
    except (RequestError, HTTPStatusError) as exc:
        raise ServiceUnavailableError(
            context={"service": "cxr", "url": _CXR_URL, "detail": str(exc)}
        ) from exc

    ml_result: Dict[str, Any] = resp.json()

    # Steps 2-5: Persistence interceptor
    db_pool = request.app.state.db_pool

    final_user_id, final_doctor_id, _user_id_is_valid_uuid = resolve_attribution(
        user_id=user_id,
        patient_id=patient_id,
        doctor_id=doctor_id,
        service_name="CXR"
    )

    if db_pool and _user_id_is_valid_uuid:
        scan_id: str = str(uuid.uuid4())

        ml_result.pop("original_img", None)

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

                    # Capture the top finding's overlay path for the canonical column
                    if xai_path is None:
                        xai_path = stored_path
                except Exception as exc:
                    logger.warning("Overlay upload failed for finding %s: %s", idx, exc)

        if has_overlays:
            if upload_success_count > 0:
                xai_status = "generated"
            else:
                xai_status = "failed"
        else:
            xai_status = "none"

        # Step 2: Upload image to Supabase Storage
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
            # Storage failure is non-fatal — we still return the ML result
            # but the image_url will be empty, and the scan row will reflect that.
            import logging
            logging.getLogger(__name__).error("Storage upload failed: %s", exc)

        # Step 3: Derive severity from confidence
        top_findings = ml_result.get("top_findings", [])
        confidence: float = float(top_findings[0].get("confidence", 0.0)) if top_findings else 0.0
        scan_status: int = ScanPersistenceService.derive_scan_status(confidence)

        # Step 4: Persist to scan_results
        try:
            await ScanPersistenceService.insert_scan_result(
                pool=db_pool,
                scan_id=scan_id,
                user_id=final_user_id,
                doctor_id=final_doctor_id,
                scan_type=_SCAN_TYPE_CXR,
                scan_status=scan_status,
                image_url=image_url,
                ai_diagnosis=str(ml_result.get("predicted_diagnoses", [""])[0] if ml_result.get("predicted_diagnoses") else ""),
                confidence=confidence,
                findings=str(ml_result.get("findings", "")),
                metadata=ml_result,
                inference_source="cloud",
                storage_path=storage_path,
                modality=ScanModality.CXR.value,
                xai_path=xai_path,
                xai_status=xai_status,
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("Failed to persist scan result: %s", exc)

            if uploaded_overlay_paths:
                try:
                    await StorageService.delete_scan_objects(
                        supabase_client=request.app.state.supabase_client,
                        bucket=gateway_config.supabase_storage_bucket,
                        user_id=final_user_id,
                        object_paths=uploaded_overlay_paths,
                    )
                except Exception as cleanup_exc:
                    logging.getLogger(__name__).warning("Orphaned overlay objects remaining after persistence failure: %s (cleanup error: %s)", uploaded_overlay_paths, cleanup_exc)

            # The endpoint does not return 200, it raises the original exception
            raise

        # Step 5: Augment response with persistence identifiers
        ml_result["scan_id"] = scan_id
        ml_result["image_url"] = image_url
        ml_result["explainability"] = {
            "status": xai_status,
            "url": build_xai_authenticated_url(xai_path),
            "modality": ScanModality.CXR.value,
        }

    return ml_result
