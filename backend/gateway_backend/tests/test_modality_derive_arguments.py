import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
from app.main import app
import httpx

@pytest.fixture(autouse=True)
def mock_dependencies():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("app.api.cxr_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert_cxr, \
         patch("app.api.ecg_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert_ecg, \
         patch("app.api.skin_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert_skin, \
         patch("app.api.cxr_router.StorageService.upload_scan_image", new_callable=AsyncMock, return_value=("mock_url", "mock_path")), \
         patch("app.api.ecg_router.StorageService.upload_scan_image", new_callable=AsyncMock, return_value=("mock_url", "mock_path")), \
         patch("app.api.skin_router.StorageService.upload_scan_image", new_callable=AsyncMock, return_value=("mock_url", "mock_path")), \
         patch("app.services.scan_persistence_service.ScanPersistenceService.derive_scan_status", return_value=1) as mock_derive, \
         patch("app.main.asyncpg.create_pool", new_callable=AsyncMock) as mock_pool, \
         patch("app.core.config.gateway_config.database_url", new="postgresql://dummy:dummy@localhost:5432/dummy"):
        # Configure the db pool mock to handle `async with db_pool.acquire()` and `await db_pool.close()`
        mock_db_pool = MagicMock()
        mock_db_pool.acquire.return_value.__aenter__.return_value = AsyncMock()
        mock_db_pool.close = AsyncMock()
        mock_pool.return_value = mock_db_pool
        
        # Setup mock responses for the ML models based on the URL being called
        def mock_post_side_effect(url, *args, **kwargs):
            req = httpx.Request("POST", url)
            if "cxr-mock" in str(url):
                return httpx.Response(200, request=req, json={"predicted_diagnoses": ["Pneumonia"], "top_findings": [{"label": "Pneumonia", "confidence": 0.9}]})
            elif "ecg-mock" in str(url):
                return httpx.Response(200, request=req, json={"predicted_class": "MI", "predicted_diagnoses": ["MI"], "top_findings": [{"label": "MI", "confidence": 0.95}]})
            elif "skin-mock" in str(url):
                return httpx.Response(200, request=req, json={"predicted_class": "Melanoma", "predicted_diagnoses": ["Melanoma"], "top_findings": [{"label": "Melanoma", "confidence": 0.88}]})
            return httpx.Response(404, request=req)
            
        mock_post.side_effect = mock_post_side_effect
        
        yield {
            "mock_derive": mock_derive,
        }

def test_cxr_passes_arguments_to_derive(mock_dependencies):
    with TestClient(app) as client:
        response = client.post("/api/v1/cxr/predict", files={"file": ("test.jpg", b"dummy")}, headers={"Authorization": "Bearer test-dev-token-secret"})
        assert response.status_code == 200, response.text
        mock_dependencies["mock_derive"].assert_called_once()
        args, kwargs = mock_dependencies["mock_derive"].call_args
        assert kwargs.get("ai_diagnosis") == "Pneumonia"
        assert kwargs.get("modality") == "cxr"

def test_ecg_passes_arguments_to_derive(mock_dependencies):
    with TestClient(app) as client:
        response = client.post("/api/v1/ecg/predict", files={"file": ("test.xml", b"dummy")}, headers={"Authorization": "Bearer test-dev-token-secret"})
        assert response.status_code == 200, response.text
        mock_dependencies["mock_derive"].assert_called_once()
        args, kwargs = mock_dependencies["mock_derive"].call_args
        assert kwargs.get("ai_diagnosis") == "MI"
        assert kwargs.get("modality") == "ecg"

def test_skin_passes_arguments_to_derive(mock_dependencies):
    with TestClient(app) as client:
        response = client.post("/api/v1/skin/predict", files={"file": ("test.jpg", b"dummy")}, headers={"Authorization": "Bearer test-dev-token-secret"})
        assert response.status_code == 200, response.text
        mock_dependencies["mock_derive"].assert_called_once()
        args, kwargs = mock_dependencies["mock_derive"].call_args
        assert kwargs.get("ai_diagnosis") == "Melanoma"
        assert kwargs.get("modality") == "skin"
