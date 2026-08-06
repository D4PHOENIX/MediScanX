import pytest
from unittest.mock import AsyncMock, MagicMock
import base64
import json
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
            data={"top_k": 1},
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
    assert call_args.kwargs["data"]["top_k"] == '1' or call_args.kwargs["data"]["top_k"] == 1


@pytest.mark.asyncio
async def test_ecg_predict_missing_file(auth_headers):
    """Test malformed/missing input: it should return the right 4xx status."""
    try:
        response = client.post(
            "/api/v1/ecg/predict",
            data={"top_k": 1},
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
            data={"top_k": 1},
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
            data={"top_k": 1},
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
    app.state.supabase_client = MagicMock()
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
            kwargs = call_args[1]
            assert kwargs["modality"] == "ecg"
            assert kwargs["scan_type"] == 0
            assert kwargs.get("xai_status", "none") == "none"
            assert kwargs.get("xai_path") is None

@pytest.mark.asyncio
async def test_ecg_xai_false(auth_headers) -> None:
    from unittest.mock import patch
    
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "predicted_class": "Normal",
        "confidence": 0.95
    }
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()
    
    with patch("app.api.ecg_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.ecg_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:
        
        mock_storage.return_value = ("url_main", "user123/scan456.png")
        
        response = client.post("/api/v1/ecg/predict", headers=auth_headers,
            files={"file": ("ecg.bin", b"data", "application/octet-stream")},
            data={"top_k": 1, "xai": "false"},
        )
        
        assert mock_client.post.call_args.kwargs["params"] == {"xai": "false"}
        assert response.status_code == 200
        
        kwargs = mock_insert.call_args[1]
        assert kwargs["xai_status"] == "none"
        assert response.json()["explainability"]["status"] == "none"

# ---------------------------------------------------------------------------
# New XAI tests (Task 3)
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_b64():
    """A minimal valid base64-encoded PNG blob."""
    return base64.b64encode(b"fake_ecg_overlay_image_data_1234567890").decode("utf-8")


@pytest.fixture
def fake_ecg_ml_data(fake_b64):
    """ECG ML response shape: gradcam_overlay + predictions with overlay_img."""
    return {
        "gradcam_overlay": fake_b64,
        "predictions": [
            {
                "label": "HYP",
                "class_idx": 4,
                "confidence": 0.5,
                "above_threshold": True,
                "threshold": 0.46,
                "overlay_img": fake_b64,
            },
            {
                "label": "NORM",
                "class_idx": 0,
                "confidence": 0.2,
                "above_threshold": False,
                "threshold": 0.49,
                "overlay_img": fake_b64,
            },
        ],
        "predicted_class": "HYP",
        "confidence": 0.5,
        "inference_time_ms": 70.1,
        "patient_id": "ecg.jpg",
    }


@pytest.mark.asyncio
async def test_ecg_overlay_objects_land_in_expected_path(auth_headers, fake_ecg_ml_data) -> None:
    """Overlay uploaded to {user_id}/{scan_id}/overlay_0.png; xai_status='generated'; xai_path set."""
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = fake_ecg_ml_data
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()

    from unittest.mock import patch
    with patch("app.api.ecg_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.ecg_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage, \
         patch("app.api.ecg_router.StorageService.delete_scan_objects", new_callable=AsyncMock) as mock_delete:

        mock_storage.side_effect = [
            ("url_overlay_0", "user123/scan456/overlay_0.png"),
            ("url_overlay_1", "user123/scan456/overlay_1.png"),
            ("url_main", "user123/scan456.png"),
        ]

        client.post(
            "/api/v1/ecg/predict",
            headers=auth_headers,
            files={"file": ("ecg.jpg", b"data", "image/jpeg")},
        )

        # First storage call is the index-0 overlay
        first_overlay_call_kwargs = mock_storage.call_args_list[0][1]
        insert_kwargs = mock_insert.call_args[1]
        expected_user_id = insert_kwargs["user_id"]
        expected_scan_id = insert_kwargs["scan_id"]

        assert first_overlay_call_kwargs["object_path"] == f"{expected_user_id}/{expected_scan_id}/overlay_0.png"
        assert insert_kwargs["xai_status"] == "generated"
        assert insert_kwargs["xai_path"] == "user123/scan456/overlay_0.png"
        assert mock_delete.call_count == 0


@pytest.mark.asyncio
async def test_ecg_overlay_upload_failure(auth_headers, fake_ecg_ml_data) -> None:
    """Upload failure yields xai_status='failed', xai_path=None, scan still persisted."""
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = fake_ecg_ml_data
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()

    from unittest.mock import patch
    with patch("app.api.ecg_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.ecg_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:

        def storage_side_effect(*args, **kwargs):
            if "overlay" in kwargs.get("object_path", ""):
                raise RuntimeError("Overlay upload failed")
            return ("url_main", "user123/scan456.png")

        mock_storage.side_effect = storage_side_effect

        response = client.post(
            "/api/v1/ecg/predict",
            headers=auth_headers,
            files={"file": ("ecg.jpg", b"data", "image/jpeg")},
        )

        assert response.status_code == 200
        kwargs = mock_insert.call_args[1]
        assert kwargs["xai_status"] == "failed"
        assert kwargs.get("xai_path") is None
        # Scan itself must still be persisted
        assert mock_insert.called


@pytest.mark.asyncio
async def test_ecg_no_overlays(auth_headers) -> None:
    """ML result with no overlay_img yields xai_status='none'."""
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "predicted_class": "Normal",
        "predictions": [{"label": "Normal", "confidence": 0.99, "class_idx": 0}],
    }
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()

    from unittest.mock import patch
    with patch("app.api.ecg_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.ecg_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:

        mock_storage.return_value = ("url_main", "user123/scan456.png")

        response = client.post(
            "/api/v1/ecg/predict",
            headers=auth_headers,
            files={"file": ("ecg.jpg", b"data", "image/jpeg")},
        )

        assert response.status_code == 200
        kwargs = mock_insert.call_args[1]
        assert kwargs["xai_status"] == "none"
        assert kwargs.get("xai_path") is None


@pytest.mark.asyncio
async def test_ecg_gradcam_overlay_absent_from_metadata(auth_headers, fake_ecg_ml_data) -> None:
    """gradcam_overlay is popped before persistence; must not appear in persisted metadata."""
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = fake_ecg_ml_data
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()

    from unittest.mock import patch
    with patch("app.api.ecg_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.ecg_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:

        mock_storage.side_effect = [
            ("url_o0", "path_o0"),
            ("url_o1", "path_o1"),
            ("url_m", "path_m"),
        ]

        client.post(
            "/api/v1/ecg/predict",
            headers=auth_headers,
            files={"file": ("ecg.jpg", b"data", "image/jpeg")},
        )

        metadata = mock_insert.call_args[1]["metadata"]
        assert "gradcam_overlay" not in metadata


@pytest.mark.asyncio
async def test_ecg_overlay_img_absent_overlay_path_present(auth_headers, fake_ecg_ml_data) -> None:
    """overlay_img replaced by overlay_path in persisted predictions."""
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = fake_ecg_ml_data
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()

    from unittest.mock import patch
    with patch("app.api.ecg_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.ecg_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:

        mock_storage.side_effect = [
            ("url_o0", "path_o0"),
            ("url_o1", "path_o1"),
            ("url_m", "path_m"),
        ]

        client.post(
            "/api/v1/ecg/predict",
            headers=auth_headers,
            files={"file": ("ecg.jpg", b"data", "image/jpeg")},
        )

        metadata = mock_insert.call_args[1]["metadata"]
        assert "overlay_img" not in metadata["top_findings"][0]
        assert "overlay_path" in metadata["top_findings"][0]


@pytest.mark.asyncio
async def test_ecg_compensating_delete_on_persistence_failure(auth_headers, fake_ecg_ml_data) -> None:
    """Orphaned storage objects deleted when the database insert raises."""
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = fake_ecg_ml_data
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()

    from unittest.mock import patch
    with patch("app.api.ecg_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.ecg_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_upload, \
         patch("app.api.ecg_router.StorageService.delete_scan_objects", new_callable=AsyncMock) as mock_delete:

        mock_upload.side_effect = [
            ("url_o0", "user123/scan456/overlay_0.png"),
            ("url_o1", "user123/scan456/overlay_1.png"),
            ("url_m", "user123/scan456.png"),
        ]
        mock_insert.side_effect = RuntimeError("Database is down")

        with pytest.raises(RuntimeError, match="Database is down"):
            client.post(
                "/api/v1/ecg/predict",
                headers=auth_headers,
                files={"file": ("ecg.jpg", b"data", "image/jpeg")},
            )

        assert mock_delete.call_count == 1
        deleted_paths = mock_delete.call_args[1]["object_paths"]
        assert "user123/scan456/overlay_0.png" in deleted_paths
        assert "user123/scan456/overlay_1.png" in deleted_paths


@pytest.mark.asyncio
async def test_ecg_metadata_size_bounded(auth_headers, fake_ecg_ml_data) -> None:
    """Persisted metadata must not contain large base64 blobs — bounded to < 4096 bytes."""
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = fake_ecg_ml_data
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()

    from unittest.mock import patch
    with patch("app.api.ecg_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.ecg_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:

        mock_storage.side_effect = [
            ("url_o0", "path_o0"),
            ("url_o1", "path_o1"),
            ("url_m", "path_m"),
        ]

        client.post(
            "/api/v1/ecg/predict",
            headers=auth_headers,
            files={"file": ("ecg.jpg", b"data", "image/jpeg")},
        )

        metadata = mock_insert.call_args[1]["metadata"]
        metadata_str = json.dumps(metadata)
        assert len(metadata_str) < 4096

@pytest.mark.asyncio
async def test_ecg_xai_status_and_path_together(auth_headers, fake_ecg_ml_data) -> None:
    """xai_status and xai_path are always set together — assert as an explicit invariant."""
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = fake_ecg_ml_data
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()

    from unittest.mock import patch
    with patch("app.api.ecg_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.ecg_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:

        mock_storage.side_effect = [
            ("url_o0", "path_o0"),
            ("url_o1", "path_o1"),
            ("url_m", "path_m"),
        ]

        response = client.post(
            "/api/v1/ecg/predict",
            headers=auth_headers,
            files={"file": ("ecg.jpg", b"data", "image/jpeg")},
        )
        assert response.status_code == 200

        kwargs = mock_insert.call_args[1]
        
        # Test invariant
        status = kwargs["xai_status"]
        path = kwargs.get("xai_path")
        
        if status == "generated":
            assert path is not None
        else:
            assert path is None

@pytest.mark.asyncio
async def test_ecg_frontend_contract_alignment(auth_headers) -> None:
    """Test that the ECG response matches the frontend contract."""
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "predicted_class": "Atrial Fibrillation",
        "confidence": 0.98,
        "predictions": [{"label": "Atrial Fibrillation", "confidence": 0.98}]
    }
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()

    from unittest.mock import patch
    with patch("app.api.ecg_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.ecg_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:

        mock_storage.return_value = ("url_main", "user123/scan456.png")

        response = client.post(
            "/api/v1/ecg/predict",
            headers=auth_headers,
            files={"file": ("ecg.jpg", b"data", "image/jpeg")},
        )

        assert response.status_code == 200
        data = response.json()

        assert "top_findings" in data
        assert "predictions" not in data
        assert data["top_findings"] == [{"label": "Atrial Fibrillation", "confidence": 0.98}]
        assert data["ai_diagnosis"] == "Atrial Fibrillation"
        assert "scan_status" in data

