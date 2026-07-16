"""Multi-modal inference tools for CXR, ECG, and Skin services.

Each tool delegates to a downstream FastAPI microservice via HTTP POST.
File payloads are constructed from a local path or identifier and sent
as multipart form data.  All network and I/O errors are caught and
returned as descriptive dictionaries so the LLM can explain the failure
to the user without crashing the graph.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Tuple

import httpx
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def _get_config() -> 'AgentConfig':
    """Lazily instantiate the service configuration on first access."""
    from app.core.config import AgentConfig
    return AgentConfig()


async def _build_file_payload(file_path_or_id: str) -> Tuple[str, bytes]:
    """Prepare a file payload for an upstream service.

    Reads the file in a thread pool to avoid blocking the async event loop.

    Args:
        file_path_or_id (str): Absolute path to a local file or an internal
            scan identifier.

    Returns:
        Tuple[str, bytes]: A tuple containing the filename and file content bytes.

    Raises:
        FileNotFoundError: If the file does not exist.
        OSError: If the file cannot be read.
    """
    filename = os.path.basename(file_path_or_id)

    def _read() -> bytes:
        with open(file_path_or_id, "rb") as fh:
            return fh.read()

    content = await asyncio.to_thread(_read)
    return filename, content


async def _post_to_service(url: str, file_path_or_id: str) -> Dict[str, Any]:
    """Post a file to an inference service and return the JSON response.

    All errors are caught and returned as structured dictionaries so the
    LLM receives a clean error message rather than an unhandled exception
    crashing the SSE stream.

    Args:
        url (str): The full URL of the downstream inference endpoint.
        file_path_or_id (str): Path to the file or scan identifier to send.

    Returns:
        Dict[str, Any]: The JSON response from the service, or an error dictionary.
    """
    try:
        filename, content = await _build_file_payload(file_path_or_id)
        files_payload = {"file": (filename, content, "application/octet-stream")}
    except (FileNotFoundError, OSError) as exc:
        logger.warning("Could not read file '%s': %s", file_path_or_id, exc)
        return {
            "error": "File not found",
            "details": f"Could not read '{file_path_or_id}': {exc}",
        }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            resp = await client.post(url, files=files_payload)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("Service %s returned HTTP %s", url, exc.response.status_code)
        return {
            "error": "Service unavailable",
            "details": f"Service {url} returned HTTP {exc.response.status_code}: {exc.response.text}",
        }
    except httpx.RequestError as exc:
        logger.warning("Could not reach %s: %s", url, exc)
        return {
            "error": "Service unavailable",
            "details": f"Could not reach {url}: {exc}",
        }


@tool
async def run_cxr_inference(image_path_or_id: str) -> Dict[str, Any]:
    """Execute chest X-ray inference using the downstream CXR service.

    Sends the image to the CXR microservice which runs a DenseNet-121
    forward pass with Grad-CAM heatmap generation and multi-label
    thresholding.

    Args:
        image_path_or_id (str): Path to a DICOM/PNG/JPG image file or an
            internal scan identifier.

    Returns:
        Dict[str, Any]: A dictionary containing the prediction results (diagnosis,
        confidence scores, heatmap), or an error dictionary.
    """
    return await _post_to_service(_get_config().cxr_service_url, image_path_or_id)


@tool
async def run_ecg_inference(file_path_or_id: str) -> Dict[str, Any]:
    """Execute ECG inference using the downstream ECG service.

    Sends the ECG recording to the ECG microservice which runs a
    CNN-BiLSTM forward pass for arrhythmia classification.

    Args:
        file_path_or_id (str): Path to a WFDB record directory (or single file)
            or an internal scan identifier.

    Returns:
        Dict[str, Any]: A dictionary containing the prediction results, or an error
        dictionary.
    """
    return await _post_to_service(_get_config().ecg_service_url, file_path_or_id)


@tool
async def run_skin_inference(image_path_or_id: str) -> Dict[str, Any]:
    """Execute skin-lesion inference using the downstream Skin service.

    Sends the dermoscopic image to the Skin microservice which runs a
    MedLiteNet/MobileNet forward pass for lesion classification.

    Args:
        image_path_or_id (str): Path to a dermoscopic image file or an internal
            scan identifier.

    Returns:
        Dict[str, Any]: A dictionary containing the prediction results, or an error
        dictionary.
    """
    return await _post_to_service(_get_config().skin_service_url, image_path_or_id)
