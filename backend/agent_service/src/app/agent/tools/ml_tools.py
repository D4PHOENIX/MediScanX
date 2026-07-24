"""Multi-modal inference tools for CXR, ECG, and Skin services.

Each tool delegates to a downstream FastAPI microservice via HTTP POST.
File payloads are securely fetched from Supabase Storage using the deterministic
storage_path derived from scan_results, ensuring no arbitrary file access is allowed.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Dict, Tuple

import asyncpg
import httpx
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from supabase._async.client import AsyncClient as SupabaseAsyncClient
from supabase._async.client import create_client

logger = logging.getLogger(__name__)


def _get_config() -> 'AgentConfig':
    """Lazily instantiate the service configuration on first access."""
    from app.core.config import AgentConfig
    return AgentConfig()


async def _get_storage_path_and_fetch(scan_id: uuid.UUID, auth_user_id: str) -> bytes:
    """Validate ownership and fetch file bytes from Supabase Storage.

    Args:
        scan_id (uuid.UUID): The internal scan identifier.
        auth_user_id (str): The injected authenticated user ID.

    Returns:
        bytes: The file content bytes.

    Raises:
        ValueError: If ownership validation fails or file is not found.
    """
    config = _get_config()
    db_url = config.database_url
    if not db_url:
        raise ValueError("DATABASE_URL is not configured.")

    storage_path = None
    try:
        conn = await asyncpg.connect(db_url)
        try:
            row = await conn.fetchrow(
                "SELECT storage_path FROM scan_results WHERE scan_id = $1 AND user_id = $2",
                scan_id, uuid.UUID(auth_user_id)
            )
            if row:
                storage_path = row["storage_path"]
        finally:
            await conn.close()
    except Exception as exc:
        logger.error("Database query failed for scan_id=%s: %s", scan_id, exc)
        raise ValueError("Failed to validate scan ownership.") from exc

    if not storage_path:
        logger.warning("Scan ownership validation failed for scan_id=%s user_id=%s", scan_id, auth_user_id)
        raise ValueError("Scan not found or access denied.")

    supabase_url = config.supabase_url
    supabase_key = config.supabase_secret_key

    if not supabase_url or not supabase_key:
        raise ValueError("Supabase credentials not configured.")

    try:
        supabase: SupabaseAsyncClient = await create_client(supabase_url, supabase_key)
        # Fetch file from storage
        res = await supabase.storage.from_("scan-images").download(storage_path)
        return res
    except Exception as exc:
        logger.error("Failed to download file from Supabase: %s", exc)
        raise ValueError("Failed to retrieve file content.") from exc


async def _post_to_service(url: str, scan_id: uuid.UUID, auth_user_id: str) -> Dict[str, Any]:
    """Post a file to an inference service and return the JSON response.

    Args:
        url (str): The full URL of the downstream inference endpoint.
        scan_id (uuid.UUID): The scan identifier to send.
        auth_user_id (str): The injected authenticated user ID.

    Returns:
        Dict[str, Any]: The JSON response from the service, or an error dictionary.
    """
    try:
        content = await _get_storage_path_and_fetch(scan_id, auth_user_id)
        # We use a dummy filename since the downstream service doesn't rely on it for processing
        files_payload = {"file": (f"{scan_id}.bin", content, "application/octet-stream")}
    except ValueError as exc:
        return {
            "error": "Validation error",
            "details": str(exc),
        }
    except Exception as exc:
        logger.warning("Could not fetch file for scan '%s': %s", scan_id, exc)
        return {
            "error": "File fetch error",
            "details": f"Could not fetch scan '{scan_id}': {exc}",
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
async def run_cxr_inference(scan_id: uuid.UUID, config: RunnableConfig) -> Dict[str, Any]:
    """Execute chest X-ray inference using the downstream CXR service.

    Args:
        scan_id (str): Internal scan identifier (UUID).
        config (RunnableConfig): Injected LangGraph config containing the auth_user_id.

    Returns:
        Dict[str, Any]: A dictionary containing the prediction results, or an error dictionary.
    """
    auth_user_id = config.get("configurable", {}).get("auth_user_id")
    if not auth_user_id:
        return {"error": "Authentication error", "details": "auth_user_id not found in context."}
    return await _post_to_service(_get_config().cxr_service_url, scan_id, auth_user_id)


@tool
async def run_ecg_inference(scan_id: uuid.UUID, config: RunnableConfig) -> Dict[str, Any]:
    """Execute ECG inference using the downstream ECG service.

    Args:
        scan_id (str): Internal scan identifier (UUID).
        config (RunnableConfig): Injected LangGraph config containing the auth_user_id.

    Returns:
        Dict[str, Any]: A dictionary containing the prediction results, or an error dictionary.
    """
    auth_user_id = config.get("configurable", {}).get("auth_user_id")
    if not auth_user_id:
        return {"error": "Authentication error", "details": "auth_user_id not found in context."}
    return await _post_to_service(_get_config().ecg_service_url, scan_id, auth_user_id)


@tool
async def run_skin_inference(scan_id: uuid.UUID, config: RunnableConfig) -> Dict[str, Any]:
    """Execute skin-lesion inference using the downstream Skin service.

    Args:
        scan_id (str): Internal scan identifier (UUID).
        config (RunnableConfig): Injected LangGraph config containing the auth_user_id.

    Returns:
        Dict[str, Any]: A dictionary containing the prediction results, or an error dictionary.
    """
    auth_user_id = config.get("configurable", {}).get("auth_user_id")
    if not auth_user_id:
        return {"error": "Authentication error", "details": "auth_user_id not found in context."}
    return await _post_to_service(_get_config().skin_service_url, scan_id, auth_user_id)
