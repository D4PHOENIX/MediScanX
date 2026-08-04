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
async def test_cxr_persists_expected_modality(auth_headers) -> None:
    from unittest.mock import patch
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"predictions": []}
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()
    
    with patch("app.api.cxr_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.cxr_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:
        mock_storage.return_value = ("url", "path")
        response = client.post("/api/v1/cxr/predict", headers=auth_headers,
            files={"file": ("xray.jpg", b"data", "image/jpeg")},
            data={"top_k": 3},
        )
        assert response.status_code == 200
        assert mock_insert.called
        kwargs = mock_insert.call_args.kwargs
        assert kwargs["modality"] == "cxr"
        assert kwargs["scan_type"] == 1

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

@pytest.fixture
def fake_ml_data():
    import base64
    fake_b64 = base64.b64encode(b"fake_image_data_for_overlay_1234567890").decode("utf-8")
    return {
        "predicted_diagnoses": ["Pneumonia"],
        "original_img": "data:image/png;base64," + fake_b64,
        "top_findings": [
            {
                "label": "Infiltrate",
                "confidence": 0.90,
                "class_idx": 4,
                "abbreviation": "INF",
                "overlay_img": fake_b64
            },
            {
                "label": "Effusion",
                "confidence": 0.85,
                "class_idx": 2,
                "abbreviation": "EFF"
            }
        ]
    }

@pytest.mark.asyncio
async def test_cxr_overlay_objects_land_in_expected_path(auth_headers, fake_ml_data) -> None:
    from unittest.mock import patch
    
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = fake_ml_data
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()
    
    with patch("app.api.cxr_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.cxr_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage, \
         patch("app.api.cxr_router.StorageService.delete_scan_objects", new_callable=AsyncMock) as mock_delete:
        
        mock_storage.side_effect = [
            ("url_overlay", "user123/scan456/overlay_0.png"),
            ("url_main", "user123/scan456.png")
        ]
        
        client.post("/api/v1/cxr/predict", headers=auth_headers,
            files={"file": ("xray.jpg", b"data", "image/jpeg")},
            data={"top_k": 3},
        )
        
        overlay_call_kwargs = mock_storage.call_args_list[0].kwargs
        kwargs = mock_insert.call_args.kwargs
        expected_user_id = kwargs["user_id"]
        expected_scan_id = kwargs["scan_id"]
        assert overlay_call_kwargs["object_path"] == f"{expected_user_id}/{expected_scan_id}/overlay_0.png"
        assert kwargs["xai_status"] == "generated"
        assert kwargs["xai_path"] == "user123/scan456/overlay_0.png"
        assert mock_delete.call_count == 0

@pytest.mark.asyncio
async def test_cxr_compensating_delete_on_persistence_failure(auth_headers, fake_ml_data) -> None:
    from unittest.mock import patch
    import pytest
    
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = fake_ml_data
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()
    
    with patch("app.api.cxr_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.cxr_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_upload, \
         patch("app.api.cxr_router.StorageService.delete_scan_objects", new_callable=AsyncMock) as mock_delete:
         
        mock_upload.side_effect = [
            ("url_overlay", "user123/scan456/overlay_0.png"),
            ("url_main", "user123/scan456.png")
        ]
        
        mock_insert.side_effect = RuntimeError("Database is down")
        
        with pytest.raises(RuntimeError, match="Database is down"):
            client.post("/api/v1/cxr/predict", headers=auth_headers,
                files={"file": ("xray.jpg", b"data", "image/jpeg")},
                data={"top_k": 3},
            )
            
        assert mock_delete.call_count == 1
        deleted_paths = mock_delete.call_args.kwargs["object_paths"]
        assert deleted_paths == ["user123/scan456/overlay_0.png"]

@pytest.mark.asyncio
async def test_cxr_compensating_delete_failure_propagates_original_exception(auth_headers, fake_ml_data) -> None:
    from unittest.mock import patch
    import pytest
    
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = fake_ml_data
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()
    
    with patch("app.api.cxr_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.cxr_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_upload, \
         patch("app.api.cxr_router.StorageService.delete_scan_objects", new_callable=AsyncMock) as mock_delete:
         
        mock_upload.side_effect = [
            ("url_overlay", "user123/scan456/overlay_0.png"),
            ("url_main", "user123/scan456.png")
        ]
        
        mock_insert.side_effect = RuntimeError("Database is down")
        mock_delete.side_effect = RuntimeError("Storage cleanup failed")
        
        with pytest.raises(RuntimeError, match="Database is down"):
            client.post("/api/v1/cxr/predict", headers=auth_headers,
                files={"file": ("xray.jpg", b"data", "image/jpeg")},
                data={"top_k": 3},
            )
            
        assert mock_delete.call_count == 1

@pytest.mark.asyncio
async def test_cxr_metadata_contains_no_large_base64_strings(auth_headers, fake_ml_data) -> None:
    from unittest.mock import patch
    import json
    
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = fake_ml_data
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()
    
    with patch("app.api.cxr_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.cxr_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:
        
        mock_storage.side_effect = [("url_o", "path_o"), ("url_m", "path_m")]
        client.post("/api/v1/cxr/predict", headers=auth_headers,
            files={"file": ("xray.jpg", b"data", "image/jpeg")}, data={"top_k": 3},
        )
        
        metadata = mock_insert.call_args.kwargs["metadata"]
        metadata_str = json.dumps(metadata)
        assert len(metadata_str) < 4096

@pytest.mark.asyncio
async def test_cxr_top_findings_retains_metadata_after_swap(auth_headers, fake_ml_data) -> None:
    from unittest.mock import patch
    
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = fake_ml_data
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()
    
    with patch("app.api.cxr_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.cxr_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:
        
        mock_storage.side_effect = [("url_o", "path_o"), ("url_m", "path_m")]
        client.post("/api/v1/cxr/predict", headers=auth_headers,
            files={"file": ("xray.jpg", b"data", "image/jpeg")}, data={"top_k": 3},
        )
        
        metadata = mock_insert.call_args.kwargs["metadata"]
        assert metadata["top_findings"][0]["label"] == "Infiltrate"
        assert metadata["top_findings"][0]["confidence"] == 0.90
        assert metadata["top_findings"][0]["class_idx"] == 4
        assert "overlay_img" not in metadata["top_findings"][0]
        assert "overlay_path" in metadata["top_findings"][0]

@pytest.mark.asyncio
async def test_cxr_original_img_is_absent_from_metadata(auth_headers, fake_ml_data) -> None:
    from unittest.mock import patch
    
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = fake_ml_data
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()
    
    with patch("app.api.cxr_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.cxr_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:
        
        mock_storage.side_effect = [("url_o", "path_o"), ("url_m", "path_m")]
        client.post("/api/v1/cxr/predict", headers=auth_headers,
            files={"file": ("xray.jpg", b"data", "image/jpeg")}, data={"top_k": 3},
        )
        
        metadata = mock_insert.call_args.kwargs["metadata"]
        assert "original_img" not in metadata

@pytest.mark.asyncio
async def test_cxr_overlay_upload_failure(auth_headers, fake_ml_data) -> None:
    from unittest.mock import patch
    
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = fake_ml_data
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()
    
    with patch("app.api.cxr_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.cxr_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:
        
        def storage_side_effect(*args, **kwargs):
            if "overlay" in kwargs.get("object_path", ""):
                raise RuntimeError("Overlay upload failed")
            return ("url_main", "user123/scan456.png")
            
        mock_storage.side_effect = storage_side_effect
        
        response = client.post("/api/v1/cxr/predict", headers=auth_headers,
            files={"file": ("xray.jpg", b"data", "image/jpeg")},
            data={"top_k": 3},
        )
        
        assert response.status_code == 200
        kwargs = mock_insert.call_args.kwargs
        metadata = kwargs["metadata"]
        assert metadata["top_findings"][0]["label"] == "Infiltrate"
        # metadata.xai key was removed in Task 1 — xai_status is the sole source of truth.
        assert "xai" not in metadata
        assert kwargs["xai_status"] == "failed"
        assert kwargs.get("xai_path") is None

@pytest.mark.asyncio
async def test_cxr_no_overlays(auth_headers) -> None:
    from unittest.mock import patch
    
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "predicted_diagnoses": ["Normal"],
        "top_findings": [{"label": "Normal", "confidence": 0.99, "class_idx": 0}]
    }
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()
    
    with patch("app.api.cxr_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.cxr_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:
        
        mock_storage.return_value = ("url_main", "user123/scan456.png")
        
        response = client.post("/api/v1/cxr/predict", headers=auth_headers,
            files={"file": ("xray.jpg", b"data", "image/jpeg")},
            data={"top_k": 3},
        )
        
        assert response.status_code == 200
        kwargs = mock_insert.call_args.kwargs
        assert kwargs["xai_status"] == "none"
        assert kwargs.get("xai_path") is None
        # metadata.xai key was removed in Task 1 — xai_status is the sole source of truth.
        assert "xai" not in kwargs["metadata"]

@pytest.mark.asyncio
async def test_cxr_ai_diagnosis_from_top_findings_invariant(auth_headers) -> None:
    from unittest.mock import patch
    
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()
    
    with patch("app.api.cxr_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.cxr_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:
        
        mock_storage.return_value = ("url_main", "user123/scan456.png")
        
        # Test 1: Two labels clear threshold. Lower-confidence at lower index.
        mock_response.json.return_value = {
            "predicted_diagnoses": ["Enlarged Cardiomediastinum", "Pleural Other"],
            "top_findings": [
                {"label": "Pleural Other", "confidence": 0.811, "class_idx": 11},
                {"label": "Enlarged Cardiomediastinum", "confidence": 0.700, "class_idx": 1}
            ]
        }
        
        client.post("/api/v1/cxr/predict", headers=auth_headers,
            files={"file": ("xray.jpg", b"data", "image/jpeg")}, data={"top_k": 3})
        
        kwargs = mock_insert.call_args.kwargs
        # Assert ai_diagnosis matches the higher-confidence label
        assert kwargs["ai_diagnosis"] == "Pleural Other"
        assert kwargs["confidence"] == 0.811
        
        mock_insert.reset_mock()
        
        # Test 2: predicted_diagnoses is empty, top_findings non-empty
        mock_response.json.return_value = {
            "predicted_diagnoses": [],
            "top_findings": [
                {"label": "Normal", "confidence": 0.5552, "class_idx": 0}
            ]
        }
        
        client.post("/api/v1/cxr/predict", headers=auth_headers,
            files={"file": ("xray.jpg", b"data", "image/jpeg")}, data={"top_k": 3})
        
        kwargs = mock_insert.call_args.kwargs
        assert kwargs["ai_diagnosis"] == "Normal"
        assert kwargs["confidence"] == 0.5552
        
        mock_insert.reset_mock()
        
        # Test 3: top_findings is empty
        mock_response.json.return_value = {
            "predicted_diagnoses": [],
            "top_findings": []
        }
        
        client.post("/api/v1/cxr/predict", headers=auth_headers,
            files={"file": ("xray.jpg", b"data", "image/jpeg")}, data={"top_k": 3})
        
        kwargs = mock_insert.call_args.kwargs
        # Assert fallback is None and 0.0
        assert kwargs["ai_diagnosis"] is None
        assert kwargs["confidence"] == 0.0
        
        # Test 4: Invariant check
        mock_insert.reset_mock()
        mock_response.json.return_value = {
            "predicted_diagnoses": ["Cardiomegaly", "Edema", "Fracture"],
            "top_findings": [
                {"label": "Edema", "confidence": 0.999, "class_idx": 5},
                {"label": "Cardiomegaly", "confidence": 0.600, "class_idx": 2},
                {"label": "Fracture", "confidence": 0.510, "class_idx": 12}
            ]
        }
        
        client.post("/api/v1/cxr/predict", headers=auth_headers,
            files={"file": ("xray.jpg", b"data", "image/jpeg")}, data={"top_k": 3})
        
        kwargs = mock_insert.call_args.kwargs
        assert kwargs["ai_diagnosis"] == "Edema"
        assert kwargs["confidence"] == 0.999
