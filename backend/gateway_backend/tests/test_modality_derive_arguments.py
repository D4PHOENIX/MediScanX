import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from app.main import app
import httpx

@pytest.fixture(autouse=True)
def mock_dependencies():
    with patch("app.api.cxr_router.AsyncClient") as mock_cxr, \
         patch("app.api.ecg_router.AsyncClient") as mock_ecg, \
         patch("app.api.skin_router.AsyncClient") as mock_skin, \
         patch("app.api.cxr_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert_cxr, \
         patch("app.api.ecg_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert_ecg, \
         patch("app.api.skin_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert_skin, \
         patch("app.api.cxr_router.ScanPersistenceService.derive_scan_status", return_value=1) as mock_derive_cxr, \
         patch("app.api.ecg_router.ScanPersistenceService.derive_scan_status", return_value=1) as mock_derive_ecg, \
         patch("app.api.skin_router.ScanPersistenceService.derive_scan_status", return_value=1) as mock_derive_skin:
        
        # Setup mock responses for the ML models
        mock_resp_cxr = httpx.Response(200, json={"predicted_diagnoses": ["Pneumonia"], "top_findings": [{"finding": "Pneumonia", "confidence": 0.9}]})
        mock_cxr.return_value.__aenter__.return_value.post.return_value = mock_resp_cxr
        
        mock_resp_ecg = httpx.Response(200, json={"predicted_diagnoses": ["MI"], "top_findings": [{"finding": "MI", "confidence": 0.95}]})
        mock_ecg.return_value.__aenter__.return_value.post.return_value = mock_resp_ecg
        
        mock_resp_skin = httpx.Response(200, json={"predicted_diagnoses": ["Melanoma"], "top_findings": [{"finding": "Melanoma", "confidence": 0.88}]})
        mock_skin.return_value.__aenter__.return_value.post.return_value = mock_resp_skin
        
        yield {
            "mock_derive_cxr": mock_derive_cxr,
            "mock_derive_ecg": mock_derive_ecg,
            "mock_derive_skin": mock_derive_skin,
        }

def test_cxr_passes_arguments_to_derive(mock_dependencies):
    client = TestClient(app)
    response = client.post("/api/v1/cxr/predict", files={"file": ("test.jpg", b"dummy")}, headers={"Authorization": "Bearer test-dev-token-secret"})
    assert response.status_code == 200, response.text
    mock_dependencies["mock_derive_cxr"].assert_called_once()
    args, kwargs = mock_dependencies["mock_derive_cxr"].call_args
    assert kwargs.get("ai_diagnosis") == "Pneumonia"
    assert kwargs.get("modality") == "cxr"

def test_ecg_passes_arguments_to_derive(mock_dependencies):
    client = TestClient(app)
    response = client.post("/api/v1/ecg/predict", files={"file": ("test.xml", b"dummy")}, headers={"Authorization": "Bearer test-dev-token-secret"})
    assert response.status_code == 200, response.text
    mock_dependencies["mock_derive_ecg"].assert_called_once()
    args, kwargs = mock_dependencies["mock_derive_ecg"].call_args
    assert kwargs.get("ai_diagnosis") == "MI"
    assert kwargs.get("modality") == "ecg"

def test_skin_passes_arguments_to_derive(mock_dependencies):
    client = TestClient(app)
    response = client.post("/api/v1/skin/predict", files={"file": ("test.jpg", b"dummy")}, headers={"Authorization": "Bearer test-dev-token-secret"})
    assert response.status_code == 200, response.text
    mock_dependencies["mock_derive_skin"].assert_called_once()
    args, kwargs = mock_dependencies["mock_derive_skin"].call_args
    assert kwargs.get("ai_diagnosis") == "Melanoma"
    assert kwargs.get("modality") == "skin"
