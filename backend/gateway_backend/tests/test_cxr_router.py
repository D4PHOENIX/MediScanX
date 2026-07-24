"""Tests for the Gateway API CXR router."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import Response
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

@pytest.mark.asyncio
async def test_cxr_stream_proxying(auth_headers) -> None:
    """Mock the downstream httpx.AsyncClient to verify the CXR proxy path."""
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "predictions": [{"label": "Pneumonia", "probability": 0.95}]
    }
    mock_response.raise_for_status = MagicMock()
    mock_client.post.return_value = mock_response
    
    app.state.http_client = mock_client
    app.state.db_pool = None
    try:
        response = client.post("/api/v1/cxr/predict", headers=auth_headers,
            files={"file": ("xray.jpg", b"fake_binary_image_data", "image/jpeg")},
            data={"top_k": 3},
        )
    finally:
        pass
    assert mock_client.post.called
    assert response.status_code == 200
    assert response.json() == {"predictions": [{"label": "Pneumonia", "probability": 0.95}]}

@pytest.mark.asyncio
async def test_upload_size_guard_returns_413(auth_headers) -> None:
    """Assert that files exceeding max_upload_bytes are rejected with HTTP 413."""
    from app.core.config import gateway_config

    # Fabricate a payload 1 byte larger than the current limit
    oversized = b"x" * (gateway_config.max_upload_bytes + 1)
    try:
        response = client.post("/api/v1/cxr/predict", headers=auth_headers,
            files={"file": ("huge.jpg", oversized, "image/jpeg")},
            data={"top_k": 1},

        )
    finally:
        pass
    assert response.status_code == 413

@pytest.mark.asyncio
async def test_upstream_service_error_envelope(auth_headers) -> None:
    """Assert that HTTPStatusError from upstream returns a properly formatted 502 JSON."""
    from httpx import HTTPStatusError, Request as HttpxRequest
    
    mock_client = AsyncMock()
    
    # Simulate an HTTP 500 from the upstream CXR service
    req = HttpxRequest("POST", "http://cxr-mock/predict")
    mock_response = Response(status_code=500, request=req)
    
    mock_client.post.side_effect = HTTPStatusError(
        "Internal Server Error",
        request=req,
        response=mock_response
    )
    
    app.state.http_client = mock_client    
    try:
        response = client.post("/api/v1/cxr/predict", headers=auth_headers,
            files={"file": ("xray.jpg", b"fake", "image/jpeg")},
            data={"top_k": 3},

        )
    finally:
        pass
    assert response.status_code == 503
    data = response.json()
    assert data.get("error") is True
    assert data.get("type") == "ServiceUnavailableError"
    assert "Service unavailable" in data.get("message", "")
    assert "context" in data
