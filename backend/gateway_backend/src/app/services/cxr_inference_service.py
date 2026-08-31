import base64
import logging
import uuid
from typing import Any, Dict, Optional

from httpx import AsyncClient, HTTPStatusError, RequestError, Response, Timeout

from app.core.config import gateway_config
from app.core.exceptions import ServiceUnavailableError
from app.models.domain import ScanModality
from app.services.scan_persistence_service import ScanPersistenceService
from app.services.storage_service import StorageService
from app.utils.attribution_utils import resolve_attribution
from app.utils.xai_utils import build_xai_authenticated_url

logger = logging.getLogger(__name__)

_SCAN_TYPE_CXR: int = 1

class CXRInferenceService:
    """Service orchestrating the Chest X-Ray diagnostic inference pipeline.
    
    Coordinates the multipart proxying of radiograph images to the downstream
    ML inference engine. It acts as an interceptor that captures the returned
    diagnostic results, securely uploads the original and Grad-CAM overlay images
    to cloud storage, and persists the diagnostic metadata into the database.
    """

    @staticmethod
    async def process_cxr_inference(
        http_client: AsyncClient,
        db_pool: Any,
        supabase_client: Any,
        content: bytes,
        filename: str,
        content_type: str,
        top_k: int,
        xai: bool,
        patient_id: Optional[str],
        doctor_id: Optional[str],
        user_id: str,
    ) -> Dict[str, Any]:
        """Proxy an inference request and orchestrate result persistence.
        
        Proxies the image to the CXR ML service, evaluates the response, and securely
        persists the scan. If database insertion fails, a compensating delete is issued
        against cloud storage to remove orphaned images and protect against storage bloat
        and inconsistent patient records.
        
        Args:
            http_client (AsyncClient): The HTTP client for calling downstream ML services.
            db_pool (Any): Database connection pool for persisting scan results.
            supabase_client (Any): Supabase client for uploading scan images.
            content (bytes): The raw image file bytes.
            filename (str): The name of the uploaded file.
            content_type (str): The MIME type of the uploaded file.
            top_k (int): Number of top diagnostic predictions to request.
            xai (bool): Whether to request Grad-CAM explainability overlays.
            patient_id (Optional[str]): Target patient identifier.
            doctor_id (Optional[str]): Attending doctor identifier.
            user_id (str): The authenticated user making the request.
            
        Returns:
            Dict[str, Any]: The diagnostic results payload augmented with persistence identifiers.
        """
        _CXR_URL: str = f"{gateway_config.cxr_service_url}/predict"
        
        # Step 1: Proxy to CXR ML service
        try:
            resp: Response = await http_client.post(
                _CXR_URL,
                files={
                    "file": (
                        filename,
                        content,
                        content_type or "application/octet-stream",
                    )
                },
                data={"top_k": top_k},
                params={"xai": "true" if xai else "false"},
                timeout=Timeout(30.0),
            )
            resp.raise_for_status()
        except (RequestError, HTTPStatusError) as exc:
            raise ServiceUnavailableError(
                context={"service": "cxr", "url": _CXR_URL, "detail": str(exc)}
            ) from exc

        ml_result: Dict[str, Any] = resp.json()

        # Steps 2-5: Persistence interceptor
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
                            supabase_client=supabase_client,
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
                    supabase_client=supabase_client,
                    bucket=gateway_config.supabase_storage_bucket,
                    user_id=final_user_id,
                    scan_id=scan_id,
                    file_bytes=content,
                    content_type=content_type,
                )
            except RuntimeError as exc:
                logger.error("Storage upload failed: %s", exc)
                if uploaded_overlay_paths:
                    try:
                        await StorageService.delete_scan_objects(
                            supabase_client=supabase_client,
                            bucket=gateway_config.supabase_storage_bucket,
                            user_id=final_user_id,
                            object_paths=uploaded_overlay_paths,
                        )
                    except Exception as cleanup_exc:
                        logger.warning("Orphaned overlay objects remaining after raw upload failure: %s (cleanup error: %s)", uploaded_overlay_paths, cleanup_exc)
                from fastapi import HTTPException
                raise HTTPException(status_code=503, detail="Raw image upload failed.") from exc

            # Step 3: Derive severity from confidence
            top = ml_result.get("top_findings") or []
            if top:
                ai_diagnosis = str(top[0].get("label", ""))
                confidence = float(top[0].get("confidence", 0.0))
            else:
                ai_diagnosis = None
                confidence = 0.0

            scan_status: int = ScanPersistenceService.derive_scan_status(
                confidence, ai_diagnosis=ai_diagnosis, modality="cxr"
            )

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
                    ai_diagnosis=ai_diagnosis,
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
                logger.error("Failed to persist scan result: %s", exc)

                if uploaded_overlay_paths:
                    try:
                        await StorageService.delete_scan_objects(
                            supabase_client=supabase_client,
                            bucket=gateway_config.supabase_storage_bucket,
                            user_id=final_user_id,
                            object_paths=uploaded_overlay_paths,
                        )
                    except Exception as cleanup_exc:
                        logger.warning("Orphaned overlay objects remaining after persistence failure: %s (cleanup error: %s)", uploaded_overlay_paths, cleanup_exc)

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
