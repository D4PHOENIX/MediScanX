import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
import httpx
from httpx import Response
import asyncio

from app.main import app
from app.core.config import gateway_config

client = TestClient(app)

@pytest.fixture
def mock_http_client():
    mock_client = MagicMock()
    mock_client.build_request = MagicMock()
    mock_client.send = AsyncMock()
    app.state.http_client = mock_client
    return mock_client

@pytest.mark.asyncio
async def test_agent_chat_success(auth_headers, mock_http_client):
    req_mock = MagicMock()
    mock_http_client.build_request.return_value = req_mock
    
    mock_response = AsyncMock()
    mock_response.status_code = 200
    
    async def mock_aiter_bytes():
        yield b"data: chunk1\n\n"
        yield b"data: chunk2\n\n"
        
    mock_response.aiter_bytes = mock_aiter_bytes
    mock_response.aclose = AsyncMock()
    mock_http_client.send.return_value = mock_response
    
    response = client.post("/api/v1/agent/chat", headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "Hello"}],
            "patient_id": "123",
            "current_scan_id": "456",
            "execution_step": "",
            "multimodal_metadata": {}
        }
    )
    
    assert response.status_code == 200
    assert b"chunk1" in response.content
    assert b"chunk2" in response.content
    assert mock_response.aclose.called

@pytest.mark.asyncio
async def test_upstream_returns_500_before_streaming(auth_headers, mock_http_client):
    req_mock = MagicMock()
    mock_http_client.build_request.return_value = req_mock
    
    mock_response = AsyncMock()
    mock_response.status_code = 500
    mock_response.aread = AsyncMock(return_value=b"Internal Server Error")
    mock_response.aclose = AsyncMock()
    mock_http_client.send.return_value = mock_response
    
    response = client.post("/api/v1/agent/chat", headers=auth_headers,
        json={"messages": []}
    )
    
    assert response.status_code == 502
    assert response.json()["detail"] == "Upstream service returned error: 500"
    assert mock_response.aclose.called
    assert "text/event-stream" not in response.headers.get("Content-Type", "")

@pytest.mark.asyncio
async def test_upstream_unreachable(auth_headers, mock_http_client):
    req_mock = MagicMock()
    mock_http_client.build_request.return_value = req_mock
    mock_http_client.send.side_effect = httpx.ConnectError("Connection refused")
    
    response = client.post("/api/v1/agent/chat", headers=auth_headers,
        json={"messages": []}
    )
    
    assert response.status_code == 503
    assert response.json()["detail"] == "Upstream service is unreachable."

@pytest.mark.asyncio
async def test_upstream_fails_mid_stream(auth_headers, mock_http_client):
    req_mock = MagicMock()
    mock_http_client.build_request.return_value = req_mock
    
    mock_response = AsyncMock()
    mock_response.status_code = 200
    
    async def mock_aiter_bytes():
        yield b"data: chunk1\n\n"
        raise httpx.ReadError("Socket closed")
        
    mock_response.aiter_bytes = mock_aiter_bytes
    mock_response.aclose = AsyncMock()
    mock_http_client.send.return_value = mock_response
    
    response = client.post("/api/v1/agent/chat", headers=auth_headers,
        json={"messages": []}
    )
    
    assert response.status_code == 200
    assert b"chunk1" in response.content
    assert b'event: error' in response.content
    assert b'"type": "UpstreamServiceError"' in response.content
    assert mock_response.aclose.called

@pytest.mark.asyncio
async def test_client_disconnects_mid_stream(auth_headers, mock_http_client):
    req_mock = MagicMock()
    mock_http_client.build_request.return_value = req_mock
    
    mock_response = AsyncMock()
    mock_response.status_code = 200
    
    async def mock_aiter_bytes():
        yield b"data: chunk1\n\n"
        raise asyncio.CancelledError("Client disconnected")
        
    mock_response.aiter_bytes = mock_aiter_bytes
    mock_response.aclose = AsyncMock()
    mock_http_client.send.return_value = mock_response
    
    # We expect the CancelledError to be propagated or handled. FastAPI's StreamingResponse
    # usually swallows it or propagates it depending on the server.
    try:
        response = client.post("/api/v1/agent/chat", headers=auth_headers,
            json={"messages": []}
        )
    except Exception:
        pass
    
    # ensure aclose is called!
    assert mock_response.aclose.called
    assert mock_http_client.aclose.called is False
