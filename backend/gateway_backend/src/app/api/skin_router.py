"""Proxy router for Dermatological (Skin-lesion) inference requests.

Routes uploaded dermatological imagery to the specialized downstream Skin
machine learning microservice for classification and risk assessment.

After receiving the ML result, the gateway intercepts the response to:
  1. Upload the raw image to Supabase Storage.
  2. Persist a structured ``scan_results`` row via ``ScanPersistenceService``.
  3. Augment the client-facing response with ``scan_id`` and ``image_url``.
"""

import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from httpx import HTTPStatusError, RequestError, AsyncClient, Response, Timeout

from app.core.config import gateway_config
from app.core.exceptions import ServiceUnavailableError
from app.core.security import get_current_user
from app.services.scan_persistence_service import ScanPersistenceService
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)

router: APIRouter = APIRouter(prefix="/skin", tags=["Skin"])

_SKIN_URL: str = f"{gateway_config.skin_service_url}/predict"

# scan_type integer for Skin Lesion (matches scan_results schema)
_SCAN_TYPE_SKIN: int = 2


@router.post("/predict")
async def skin_predict(
    request: Request,
    file: UploadFile = File(...),
    top_k: int = Form(3),
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

    #  Step 1: Proxy to Skin ML service 
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
            timeout=Timeout(30.0),
        )
        resp.raise_for_status()
    except (RequestError, HTTPStatusError) as exc:
        raise ServiceUnavailableError(
            context={"service": "skin", "url": _SKIN_URL, "detail": str(exc)}
        ) from exc

    ml_result: Dict[str, Any] = resp.json()

    #  Steps 2–5: Persistence interceptor 
    db_pool = request.app.state.db_pool

    # Guard: user_id must be a valid UUID before any DB/Storage interaction.
    # In DEV_MODE, get_current_user returns 'dev-user-uuid' which fails asyncpg's ::uuid cast.
    _user_id_is_valid_uuid = True
    try:
        uuid.UUID(user_id)
    except ValueError:
        _user_id_is_valid_uuid = False
        logger.warning(
            "Skin persistence skipped: user_id '%s' is not a valid UUID. "
            "This is expected in DEV_MODE (dev-token). "
            "Use a real Supabase JWT to test persistence.",
            user_id,
        )

    if db_pool and _user_id_is_valid_uuid:
        scan_id: str = str(uuid.uuid4())

        # Step 2: Upload image to Supabase Storage
        image_url: str = ""
        try:
            image_url = await StorageService.upload_scan_image(
                http_client=client,
                supabase_url=gateway_config.supabase_url,
                service_role_key=gateway_config.supabase_service_role_key,
                bucket=gateway_config.supabase_storage_bucket,
                user_id=user_id,
                scan_id=scan_id,
                file_bytes=content,
                content_type=file.content_type,
            )
        except RuntimeError as exc:
            import logging
            logging.getLogger(__name__).error("Storage upload failed: %s", exc)

        # Step 3: Derive severity from confidence
        top_findings = ml_result.get("top_findings", [])
        confidence: float = float(top_findings[0].get("confidence", 0.0)) if top_findings else 0.0
        scan_status: int = ScanPersistenceService.derive_scan_status(confidence)

        # Step 4: Persist to scan_results
        await ScanPersistenceService.insert_scan_result(
            pool=db_pool,
            scan_id=scan_id,
            user_id=user_id,
            doctor_id=doctor_id,
            scan_type=_SCAN_TYPE_SKIN,
            scan_status=scan_status,
            image_url=image_url,
            ai_diagnosis=str(ml_result.get("predicted_class", "")),
            confidence=confidence,
            findings=str(ml_result.get("findings", "")),
            metadata=ml_result,
            inference_source="cloud",
        )

        # Step 5: Augment response with persistence identifiers
        ml_result["scan_id"] = scan_id
        ml_result["image_url"] = image_url

    return ml_result
