import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from app.main import app
from app.core.security import get_current_user
from app.services.qr_service import QRGenerator

client = TestClient(app)

@pytest.mark.asyncio
async def test_generate_referral_success() -> None:
    """Test generating a referral returns the correct QR payload."""
    app.dependency_overrides[get_current_user] = lambda: "test_user_uuid"
    
    mock_qr_service = MagicMock(spec=QRGenerator)
    mock_qr_service.generate_referral_qr.return_value = "base64_qr_string"
    app.dependency_overrides[QRGenerator] = lambda: mock_qr_service
    
    try:
        response = client.post(
            "/api/v1/referral/generate",
            json={
                "patient_id": "patient-123",
                "diagnostic_summary": "High risk of pneumonia"
            }
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(QRGenerator, None)

    assert response.status_code == 200
    assert response.json() == {"qr_payload": "base64_qr_string"}
    mock_qr_service.generate_referral_qr.assert_called_once_with("patient-123", "High risk of pneumonia")

@pytest.mark.asyncio
async def test_generate_referral_invalid_input() -> None:
    """Test generating a referral with missing fields returns 422."""
    app.dependency_overrides[get_current_user] = lambda: "test_user_uuid"
    
    try:
        response = client.post(
            "/api/v1/referral/generate",
            json={
                "patient_id": "patient-123"
                # Missing diagnostic_summary
            }
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 422
