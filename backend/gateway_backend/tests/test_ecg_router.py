import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import Response, HTTPStatusError, Request as HttpxRequest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import gateway_config

client = TestClient(app)

@pytest.mark.asyncio
async def test_ecg_predict_valid_input(auth_headers):
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
    try:
        response = client.post(
                "/api/v1/ecg/predict", 
            files={"file": ("ecg.csv", b"fake_ecg_data", "text/csv")},
            data={"top_k": 3},
                headers=auth_headers,
                

        )
    finally:
        pass
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
async def test_ecg_predict_missing_file(auth_headers):
    """Test malformed/missing input: it should return the right 4xx status."""
    try:
        response = client.post(
            "/api/v1/ecg/predict",
            data={"top_k": 3},
                headers=auth_headers,
                

        )
    finally:
        pass
    assert response.status_code == 422  # Unprocessable Entity


@pytest.mark.asyncio
async def test_ecg_predict_too_large(auth_headers):
    """Test malformed/missing input: it should return the right 4xx status."""
    oversized = b"x" * (gateway_config.max_upload_bytes + 1)
    try:
        response = client.post(
                "/api/v1/ecg/predict", 
            files={"file": ("huge.csv", oversized, "text/csv")},
            data={"top_k": 1},
                headers=auth_headers,
                

        )
    finally:
        pass
    assert response.status_code == 413  # Request Entity Too Large


@pytest.mark.asyncio
async def test_ecg_predict_upstream_error(auth_headers):
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
    try:
        response = client.post(
                "/api/v1/ecg/predict", 
            files={"file": ("ecg.csv", b"fake", "text/csv")},
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
async def test_ecg_predict_422_forwarding(auth_headers):
    """Test that a 422 from upstream is forwarded directly to the client."""
    mock_client = AsyncMock()
    
    req = HttpxRequest("POST", f"{gateway_config.ecg_service_url}/predict")
    mock_response = Response(status_code=422, request=req, json={
        "error": "digitization_failed",
        "message": "This ECG image could not be read reliably.",
        "leads_failed": ["I"],
        "coverage": {"I": 0.1},
        "guidance": "Ensure even lighting..."
    })
    
    mock_client.post.side_effect = HTTPStatusError(
        "Unprocessable Entity",
        request=req,
        response=mock_response
    )
    
    app.state.http_client = mock_client    
    try:
        response = client.post(
            "/api/v1/ecg/predict", 
            files={"file": ("ecg.csv", b"fake", "text/csv")},
            data={"top_k": 3},
            headers=auth_headers,
        )
    finally:
        pass
    assert response.status_code == 422
    data = response.json()
    assert data.get("error") == "digitization_failed"
    assert data.get("leads_failed") == ["I"]
    assert data.get("coverage") == {"I": 0.1}

@pytest.mark.asyncio
async def test_ecg_persists_expected_modality(auth_headers) -> None:
    from unittest.mock import patch
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"predictions": []}
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    
    with patch("app.api.ecg_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.ecg_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:
        mock_storage.return_value = ("url", "path")
        
        # 1) Image path
        response_img = client.post("/api/v1/ecg/predict", headers=auth_headers,
            files={"file": ("ecg.jpg", b"data", "image/jpeg")},
        )
        assert response_img.status_code == 200
        
        # 2) WFDB path
        response_wfdb = client.post("/api/v1/ecg/predict", headers=auth_headers,
            files={"file": ("ecg.csv", b"data", "text/csv")},
        )
        assert response_wfdb.status_code == 200
        
        assert mock_insert.call_count == 2
        for call_args in mock_insert.call_args_list:
            kwargs = call_args.kwargs
            assert kwargs["modality"] == "ecg"
            assert kwargs["scan_type"] == 0
            assert kwargs.get("xai_status", "none") == "none"
            assert kwargs.get("xai_path") is None
