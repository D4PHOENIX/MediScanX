import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import gateway_config

client = TestClient(app)

@pytest.mark.asyncio
async def test_agent_chat_success(auth_headers):
    """Test that the orchestration endpoint routes to the agent correctly and passes through the expected fields."""
    with patch("app.api.agent_router.httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        mock_response = AsyncMock()
        mock_response.status_code = 200
        
        async def mock_aiter_bytes():
            yield b"data: chunk1\n\n"
            yield b"data: chunk2\n\n"
        
        mock_response.aiter_bytes = mock_aiter_bytes
        
        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__.return_value = mock_response
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)
        try:
            response = client.post("/api/v1/agent/chat", headers=auth_headers,
                json={
                    "messages": [{"role": "user", "content": "Hello"}],
                    "patient_id": "123",
                    "current_scan_id": "456",
                    "execution_step": "",
                    "multimodal_metadata": {}
                }
            )
        finally:
            pass
        assert response.status_code == 200
        assert b"chunk1" in response.content
        assert b"chunk2" in response.content
        
        assert mock_client.stream.called
        call_args = mock_client.stream.call_args
        assert call_args.args[0] == "POST"
        assert call_args.args[1] == f"{gateway_config.agent_service_url}/chat"
        assert call_args.kwargs["json"]["messages"][0]["content"] == "Hello"
        assert call_args.kwargs["json"]["patient_id"] == "123"
        assert call_args.kwargs["headers"]["Authorization"] == auth_headers["Authorization"]


@pytest.mark.asyncio
async def test_agent_chat_failure(auth_headers):
    """Handle an agent failure gracefully."""
    with patch("app.api.agent_router.httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_response.aread.return_value = b"Internal Server Error"
        
        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__.return_value = mock_response
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)
        try:
            response = client.post("/api/v1/agent/chat", headers=auth_headers,
                json={
                    "messages": [{"role": "user", "content": "Fail"}],
                    "patient_id": "",
                    "current_scan_id": "",
                    "execution_step": "",
                    "multimodal_metadata": {}
                }
            )
        finally:
            pass
        assert response.status_code == 200
        assert b"error" in response.content
        assert b"Agent service returned HTTP 500" in response.content
