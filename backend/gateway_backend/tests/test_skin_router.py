import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import Response, HTTPStatusError, Request as HttpxRequest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import gateway_config

client = TestClient(app)

@pytest.mark.asyncio
async def test_skin_predict_valid_input(auth_headers):
    """Test valid-input inference: it should return the expected response shape."""
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "predicted_class": "Melanoma",
        "top_findings": [{"confidence": 0.89}],
        "findings": "Malignant"
    }
    mock_response.raise_for_status = MagicMock()
    mock_client.post.return_value = mock_response
    
    app.state.http_client = mock_client
    app.state.db_pool = None
    try:
        response = client.post(
                "/api/v1/skin/predict", 
            files={"file": ("skin.jpg", b"fake_skin_data", "image/jpeg")},
            data={"top_k": 3},
                headers=auth_headers,
                

        )
    finally:
        pass
    assert mock_client.post.called
    assert response.status_code == 200
    assert response.json() == {
        "predicted_class": "Melanoma",
        "top_findings": [{"confidence": 0.89}],
        "findings": "Malignant"
    }
    
    # Assert that the model-inference layer is called with the correctly-shaped payload
    call_args = mock_client.post.call_args
    url = call_args.args[0]
    assert url == f"{gateway_config.skin_service_url}/predict"
    assert "file" in call_args.kwargs["files"]
    assert call_args.kwargs["files"]["file"][1] == b"fake_skin_data"
    assert call_args.kwargs["data"]["top_k"] == '3' or call_args.kwargs["data"]["top_k"] == 3


@pytest.mark.asyncio
async def test_skin_predict_missing_file(auth_headers):
    """Test malformed/missing input: it should return the right 4xx status."""
    try:
        response = client.post(
            "/api/v1/skin/predict",
            data={"top_k": 3},
                headers=auth_headers,
                

        )
    finally:
        pass
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_skin_predict_too_large(auth_headers):
    """Test malformed/missing input: it should return the right 4xx status."""
    oversized = b"x" * (gateway_config.max_upload_bytes + 1)
    try:
        response = client.post(
                "/api/v1/skin/predict", 
            files={"file": ("huge.jpg", oversized, "image/jpeg")},
            data={"top_k": 1},
                headers=auth_headers,
                

        )
    finally:
        pass
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_skin_predict_upstream_error(auth_headers):
    """Test that a raised inference error is handled."""
    mock_client = AsyncMock()
    
    req = HttpxRequest("POST", f"{gateway_config.skin_service_url}/predict")
    mock_response = Response(status_code=500, request=req)
    
    mock_client.post.side_effect = HTTPStatusError(
        "Internal Server Error",
        request=req,
        response=mock_response
    )
    
    app.state.http_client = mock_client    
    try:
        response = client.post(
                "/api/v1/skin/predict", 
            files={"file": ("skin.jpg", b"fake", "image/jpeg")},
            data={"top_k": 3},
                headers=auth_headers,
                

        )
    finally:
        pass
    assert response.status_code == 503
    data = response.json()
    assert data.get("error") is True
    assert data.get("type") == "ServiceUnavailableError"

@pytest.mark.asyncio
async def test_skin_persists_expected_modality(auth_headers) -> None:
    from unittest.mock import patch
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"predictions": []}
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    
    with patch("app.api.skin_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.skin_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:
        mock_storage.return_value = ("url", "path")
        response = client.post("/api/v1/skin/predict", headers=auth_headers,
            files={"file": ("skin.jpg", b"data", "image/jpeg")},
        )
        assert response.status_code == 200
        assert mock_insert.called
        kwargs = mock_insert.call_args.kwargs
        assert kwargs["modality"] == "skin"
        assert kwargs["scan_type"] == 2
