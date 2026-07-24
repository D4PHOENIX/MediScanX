import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.runnables import RunnableConfig

from app.agent.tools.ml_tools import run_cxr_inference, run_ecg_inference, run_skin_inference

@pytest.fixture
def dummy_scan_id() -> uuid.UUID:
    return uuid.uuid4()

@pytest.fixture
def dummy_user_id() -> str:
    return str(uuid.uuid4())

@pytest.fixture
def dummy_config(dummy_user_id: str) -> RunnableConfig:
    return RunnableConfig(configurable={"auth_user_id": dummy_user_id})

@pytest.fixture
def mock_supabase() -> MagicMock:
    mock_client = MagicMock()
    mock_storage = MagicMock()
    mock_from = MagicMock()
    mock_from.download = AsyncMock(return_value=b"fake-image-bytes")
    mock_storage.from_.return_value = mock_from
    mock_client.storage = mock_storage
    return mock_client

@pytest.mark.asyncio
@patch("app.agent.tools.ml_tools.create_client", new_callable=AsyncMock)
@patch("app.agent.tools.ml_tools.asyncpg.connect", new_callable=AsyncMock)
@patch("app.agent.tools.ml_tools.httpx.AsyncClient", autospec=True)
async def test_run_cxr_inference_success(
    mock_httpx_client: MagicMock,
    mock_pg_connect: AsyncMock,
    mock_create_client: AsyncMock,
    dummy_scan_id: uuid.UUID,
    dummy_config: RunnableConfig,
    mock_supabase: MagicMock,
) -> None:
    # 1. Mock Database
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {"storage_path": "test/path/to/image.dcm"}
    mock_pg_connect.return_value = mock_conn

    # 2. Mock Supabase
    mock_create_client.return_value = mock_supabase

    # 3. Mock HTTPX
    mock_client_instance = AsyncMock()
    mock_client_instance.__aenter__.return_value = mock_client_instance
    mock_response = MagicMock()
    mock_response.json.return_value = {"disease_probabilities": {"Pneumonia": 0.95}}
    mock_response.raise_for_status = MagicMock()
    mock_client_instance.post.return_value = mock_response
    mock_httpx_client.return_value = mock_client_instance

    # Run inference
    result = await run_cxr_inference.ainvoke({"scan_id": str(dummy_scan_id)}, config=dummy_config)

    # Assertions
    assert "error" not in result
    assert result == {"disease_probabilities": {"Pneumonia": 0.95}}

    # Verify ownership predicate logic was applied in DB
    mock_conn.fetchrow.assert_called_once()
    called_query = mock_conn.fetchrow.call_args[0][0]
    assert "user_id = $2" in called_query
    
    # Verify we hit supabase storage
    mock_supabase.storage.from_.assert_called_with("scan-images")
    mock_supabase.storage.from_().download.assert_called_with("test/path/to/image.dcm")

    # Verify no open() was used, bytes were posted directly
    mock_client_instance.post.assert_called_once()
    post_kwargs = mock_client_instance.post.call_args[1]
    assert "files" in post_kwargs
    files_payload = post_kwargs["files"]["file"]
    # files_payload should be (filename, bytes, content_type)
    assert files_payload[1] == b"fake-image-bytes"

@pytest.mark.asyncio
async def test_run_inference_missing_auth(dummy_scan_id: uuid.UUID) -> None:
    config = RunnableConfig(configurable={}) # Missing auth_user_id
    result = await run_ecg_inference.ainvoke({"scan_id": str(dummy_scan_id)}, config=config)
    assert "error" in result
    assert "Authentication error" in result["error"]
