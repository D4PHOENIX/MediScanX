import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import Response, HTTPStatusError, Request as HttpxRequest
from fastapi.testclient import TestClient

from app.main import app
from app.core.security import get_current_user
from app.core.config import gateway_config

client = TestClient(app)

@pytest.mark.asyncio
async def test_ecg_predict_valid_input():
    """Test valid-input inference: it should return the expected response shape."""
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "predicted_class": "Atrial Fibrillation",
        "predicted_confidence": 0.98,
        "findings": "Irregular rhythm detected"
    }
    mock_response.raise_for_status = MagicMock()
    mock_client.post.return_value = mock_response
    
    app.state.http_client = mock_client
    app.state.db_pool = None

    app.dependency_overrides[get_current_user] = lambda: "test_user_uuid"
    try:
        response = client.post(
            "/api/v1/ecg/predict",
            files={"file": ("ecg.csv", b"fake_ecg_data", "text/csv")},
            data={"top_k": 3},
            headers={"Authorization": "Bearer fake_token"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert mock_client.post.called
    assert response.status_code == 200
    assert response.json() == {
        "predicted_class": "Atrial Fibrillation",
        "predicted_confidence": 0.98,
        "findings": "Irregular rhythm detected"
    }
    
    # Assert that the model-inference layer is called with the correctly-shaped payload
    call_args = mock_client.post.call_args
    url = call_args.args[0]
    assert url == f"{gateway_config.ecg_service_url}/predict"
    assert "file" in call_args.kwargs["files"]
    assert call_args.kwargs["files"]["file"][1] == b"fake_ecg_data"
    assert call_args.kwargs["data"]["top_k"] == '3' or call_args.kwargs["data"]["top_k"] == 3


@pytest.mark.asyncio
async def test_ecg_predict_missing_file():
    """Test malformed/missing input: it should return the right 4xx status."""
    app.dependency_overrides[get_current_user] = lambda: "test_user_uuid"
    try:
        response = client.post(
            "/api/v1/ecg/predict",
            data={"top_k": 3},
            headers={"Authorization": "Bearer fake_token"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 422  # Unprocessable Entity


@pytest.mark.asyncio
async def test_ecg_predict_too_large():
    """Test malformed/missing input: it should return the right 4xx status."""
    oversized = b"x" * (gateway_config.max_upload_bytes + 1)
    app.dependency_overrides[get_current_user] = lambda: "test_user_uuid"
    try:
        response = client.post(
            "/api/v1/ecg/predict",
            files={"file": ("huge.csv", oversized, "text/csv")},
            data={"top_k": 1},
            headers={"Authorization": "Bearer fake_token"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 413  # Request Entity Too Large


@pytest.mark.asyncio
async def test_ecg_predict_upstream_error():
    """Test that a raised inference error is handled."""
    mock_client = AsyncMock()
    
    req = HttpxRequest("POST", f"{gateway_config.ecg_service_url}/predict")
    mock_response = Response(status_code=500, request=req)
    
    mock_client.post.side_effect = HTTPStatusError(
        "Internal Server Error",
        request=req,
        response=mock_response
    )
    
    app.state.http_client = mock_client
    app.dependency_overrides[get_current_user] = lambda: "test_user_uuid"
    
    try:
        response = client.post(
            "/api/v1/ecg/predict",
            files={"file": ("ecg.csv", b"fake", "text/csv")},
            data={"top_k": 3},
            headers={"Authorization": "Bearer fake_token"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 503
    data = response.json()
    assert data.get("error") is True
    assert data.get("type") == "ServiceUnavailableError"
