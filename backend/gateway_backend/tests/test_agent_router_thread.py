import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
client = TestClient(app)

@pytest.fixture
def mock_http_client():
    mock_client = MagicMock()
    mock_client.build_request = MagicMock()
    mock_client.send = AsyncMock()
    app.state.http_client = mock_client
    return mock_client

@pytest.mark.asyncio
async def test_g1_valid_thread_id_canonicalised(auth_headers, mock_http_client):
    import uuid
    upper_uuid = str(uuid.uuid4()).upper()
    
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.aiter_bytes = AsyncMock(return_value=iter([]))
    mock_response.aclose = AsyncMock()
    mock_http_client.send.return_value = mock_response

    response = client.post("/api/v1/agent/chat", headers=auth_headers, json={
        "messages": [{"role": "user", "content": "hi"}],
        "thread_id": upper_uuid
    })
    
    assert response.status_code == 200
    mock_http_client.build_request.assert_called_once()
    body = mock_http_client.build_request.call_args[1]["json"]
    assert body["thread_id"] == upper_uuid.lower()

@pytest.mark.asyncio
async def test_g2_invalid_thread_id(auth_headers):
    response = client.post("/api/v1/agent/chat", headers=auth_headers, json={
        "messages": [{"role": "user", "content": "hi"}],
        "thread_id": "abc"
    })
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_g3_thread_id_forwarded(auth_headers, mock_http_client):
    import uuid
    target = str(uuid.uuid4())
    
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.aiter_bytes = AsyncMock(return_value=iter([]))
    mock_response.aclose = AsyncMock()
    mock_http_client.send.return_value = mock_response

    response = client.post("/api/v1/agent/chat", headers=auth_headers, json={
        "messages": [{"role": "user", "content": "hi"}],
        "thread_id": target
    })
    
    assert response.status_code == 200
    mock_http_client.build_request.assert_called_once()
    body = mock_http_client.build_request.call_args[1]["json"]
    assert "thread_id" in body
    assert body["thread_id"] == target

@pytest.mark.asyncio
async def test_g4_thread_id_omitted(auth_headers, mock_http_client):
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.aiter_bytes = AsyncMock(return_value=iter([]))
    mock_response.aclose = AsyncMock()
    mock_http_client.send.return_value = mock_response

    response = client.post("/api/v1/agent/chat", headers=auth_headers, json={
        "messages": [{"role": "user", "content": "hi"}]
    })
    
    assert response.status_code == 200
    mock_http_client.build_request.assert_called_once()
    body = mock_http_client.build_request.call_args[1]["json"]
    assert body.get("thread_id") is None


@pytest.mark.asyncio
async def test_g5_empty_patient_scan_id_forwarded(auth_headers, mock_http_client):
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.aiter_bytes = AsyncMock(return_value=iter([]))
    mock_response.aclose = AsyncMock()
    mock_http_client.send.return_value = mock_response

    response = client.post("/api/v1/agent/chat", headers=auth_headers, json={
        "messages": [{"role": "user", "content": "hi"}],
        "patient_id": "",
        "current_scan_id": ""
    })
    
    assert response.status_code == 200
    mock_http_client.build_request.assert_called_once()
    body = mock_http_client.build_request.call_args[1]["json"]
    # The gateway scrubs empty strings to None
    assert body.get("patient_id") is None
    assert body.get("current_scan_id") is None
