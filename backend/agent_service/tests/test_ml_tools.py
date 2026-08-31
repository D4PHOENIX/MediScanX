import uuid
import logging
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import ValidationError

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

    # Run inference with open patched
    with patch("builtins.open") as mock_open:
        result = await run_cxr_inference.ainvoke({"scan_id": str(dummy_scan_id)}, config=dummy_config)
        mock_open.assert_not_called()

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

@pytest.mark.asyncio
async def test_run_inference_missing_auth(dummy_scan_id: uuid.UUID) -> None:
    config = RunnableConfig(configurable={}) # Missing auth_user_id
    result = await run_ecg_inference.ainvoke({"scan_id": str(dummy_scan_id)}, config=config)
    assert "error" in result
    assert "Authentication error" in result["error"]

@pytest.mark.asyncio
async def test_path_shaped_input_rejected_by_schema(dummy_config: RunnableConfig) -> None:
    # Path-shaped input should fail Pydantic UUID validation before tool logic executes
    with pytest.raises(ValidationError):
        await run_cxr_inference.ainvoke({"scan_id": "/etc/passwd"}, config=dummy_config)

@pytest.mark.asyncio
@patch("app.agent.tools.ml_tools.asyncpg.connect", new_callable=AsyncMock)
async def test_cross_tenant_attempt_logs_and_fails(
    mock_pg_connect: AsyncMock,
    dummy_scan_id: uuid.UUID,
    dummy_config: RunnableConfig,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # 1. Mock Database to simulate "not found or access denied"
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = None
    mock_pg_connect.return_value = mock_conn

    with caplog.at_level(logging.WARNING):
        result = await run_cxr_inference.ainvoke({"scan_id": str(dummy_scan_id)}, config=dummy_config)
    
    # Assert generic not-found result
    assert result == {
        "error": "Validation error",
        "details": "Scan not found or access denied.",
    }
    
    # Assert logs
    auth_user_id = dummy_config.get("configurable", {}).get("auth_user_id")
    expected_log = f"Scan ownership validation failed for scan_id={dummy_scan_id} user_id={auth_user_id}"
    assert expected_log in caplog.text

