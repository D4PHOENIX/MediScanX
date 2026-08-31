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
from app.services.cxr_inference_service import CXRInferenceService

logger = logging.getLogger(__name__)

router: APIRouter = APIRouter(prefix="/cxr", tags=["CXR"])

_CXR_URL: str = f"{gateway_config.cxr_service_url}/predict"

# scan_type integer for Chest X-Ray (matches scan_results schema)
_SCAN_TYPE_CXR: int = 1


@router.post("/predict")
async def cxr_predict(
    request: Request,
    file: UploadFile = File(...),
    top_k: int = Form(1),
    xai: bool = Form(True),
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

    return await CXRInferenceService.process_cxr_inference(
        http_client=request.app.state.http_client,
        db_pool=request.app.state.db_pool,
        supabase_client=request.app.state.supabase_client,
        content=content,
        filename=file.filename,
        content_type=file.content_type,
        top_k=top_k,
        xai=xai,
        patient_id=patient_id,
        doctor_id=doctor_id,
        user_id=user_id,
    )
