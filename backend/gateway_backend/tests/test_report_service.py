import pytest
from unittest.mock import AsyncMock, MagicMock
from app.main import app
from app.services.report_service import ReportGenerator
import app.api.report_router as report_router
from fastapi.testclient import TestClient

client = TestClient(app)

def test_pdf_generation_produces_valid_artifact():
    # Setup Generator
    gen = ReportGenerator()
    
    # Mock data
    patient_id = "patient-123"
    scan_metadata = [{"id": "scan-1", "modality": "X-Ray", "class": "Pneumonia", "timestamp": "2026-07-22T00:00:00Z"}]
    llm_summary = "The patient has pneumonia."
    
    # Generate the story (without QR code for simplicity in base artifact test)
    pdf_bytes = gen._build_pdf_story(patient_id, scan_metadata, llm_summary, qr_img=None)
    
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF"), "Generated PDF should be a valid PDF artifact starting with %PDF"


@pytest.mark.asyncio
async def test_download_endpoint_existing_report_redirects():
    mock_supabase_client = MagicMock()
    mock_bucket = AsyncMock()
    mock_supabase_client.storage.from_.return_value = mock_bucket
    mock_bucket.create_signed_url.return_value = {"signedURL": "https://signed.mock/report.pdf"}
    
    app.state.supabase_client = mock_supabase_client
    
    patient_id = "patient-valid-456"
    file_path = "patient-valid-456_hash_report.pdf"
    
    # Inject report path into router state
    report_router._report_paths[patient_id] = file_path
    
    response = client.get(
        f"/api/v1/reports/download/{patient_id}",
        headers={"Authorization": "Bearer test-dev-token-secret"},
        follow_redirects=False # Ensure we capture the 307 redirect
    )
    
    # Since it's a RedirectResponse, status should be 307
    assert response.status_code == 307
    assert response.headers["location"] == "https://signed.mock/report.pdf"
    
    mock_bucket.create_signed_url.assert_awaited_once_with(file_path, 86400)
    
    # Clean up
    del report_router._report_paths[patient_id]


@pytest.mark.asyncio
async def test_download_endpoint_missing_report_returns_404():
    response = client.get(
        "/api/v1/reports/download/patient-missing",
        headers={"Authorization": "Bearer test-dev-token-secret"}
    )
    
    assert response.status_code == 404
    data = response.json()
    # The default HTTP exception handler might return {"detail": "..."}
    assert "detail" in data
    assert "Report not found" in data["detail"]
