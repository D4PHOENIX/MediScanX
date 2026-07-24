import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from app.main import app
from app.services.qr_service import QRGenerator

client = TestClient(app)

@pytest.mark.asyncio
async def test_generate_referral_success(auth_headers) -> None:
    """Test generating a referral returns the correct QR payload."""    
    mock_qr_service = MagicMock(spec=QRGenerator)
    mock_qr_service.generate_referral_qr.return_value = "base64_qr_string"
    app.dependency_overrides[QRGenerator] = lambda: mock_qr_service
    
    try:
        response = client.post("/api/v1/referral/generate", headers=auth_headers,
            json={
                "patient_id": "patient-123",
                "diagnostic_summary": "High risk of pneumonia"
            }
        )
    finally:        app.dependency_overrides.pop(QRGenerator, None)

    assert response.status_code == 200
    assert response.json() == {"qr_payload": "base64_qr_string"}
    mock_qr_service.generate_referral_qr.assert_called_once_with("patient-123", "High risk of pneumonia")

@pytest.mark.asyncio
async def test_generate_referral_invalid_input(auth_headers) -> None:
    """Test generating a referral with missing fields returns 422."""    
    try:
        response = client.post("/api/v1/referral/generate", headers=auth_headers,
            json={
                "patient_id": "patient-123"
                # Missing diagnostic_summary
            }
        )
    finally:
        pass
    assert response.status_code == 422
