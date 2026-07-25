import pytest
from fastapi.testclient import TestClient
import uuid
from app.main import app
from unittest.mock import AsyncMock, MagicMock

client = TestClient(app)

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "route, method_kwargs",
    [
        (
            "/api/v1/cxr/predict",
            {
                "data": {"symptoms": "cough"},
                "files": {"file": ("test.dcm", b"dummy", "application/dicom")},
            },
        ),
        (
            "/api/v1/ecg/predict",
            {
                "data": {},
                "files": {"file": ("test.xml", b"dummy", "text/xml")},
            },
        ),
        (
            "/api/v1/skin/predict",
            {
                "data": {"lesion_location": "arm"},
                "files": {"file": ("test.jpg", b"dummy", "image/jpeg")},
            },
        ),
        (
            "/api/v1/sync/edge-inference",
            {
                "data": {
                    "scan_id": str(uuid.uuid4()),
                    "scan_type": 1,
                    "scan_status": 0,
                    "ai_diagnosis": "Normal",
                    "confidence": 0.99,
                },
                "files": {"file": ("test.jpg", b"dummy", "image/jpeg")},
            },
        ),
    ],
)
async def test_cross_user_patient_id_returns_403(auth_headers, route, method_kwargs):
    wrong_user_id = str(uuid.uuid4())
    app.state.http_client = AsyncMock()
    mock_acquire_ctx = MagicMock()
    mock_acquire_ctx.__aenter__ = AsyncMock()
    mock_acquire_ctx.__aexit__ = AsyncMock()
    app.state.db_pool = MagicMock()
    app.state.db_pool.acquire.return_value = mock_acquire_ctx
    app.state.supabase_client = AsyncMock()
    
    # We inject the wrong user_id to trigger the 403
    method_kwargs["data"]["patient_id"] = wrong_user_id
    
    resp = client.post(
        route,
        headers=auth_headers,
        **method_kwargs
    )
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}. Response: {resp.json() if resp.content else ''}"


@pytest.mark.asyncio
async def test_client_supplied_user_id_or_doctor_id_sync_route_returns_422(auth_headers, test_user_id):
    app.state.http_client = AsyncMock()
    mock_acquire_ctx = MagicMock()
    mock_acquire_ctx.__aenter__ = AsyncMock()
    mock_acquire_ctx.__aexit__ = AsyncMock()
    app.state.db_pool = MagicMock()
    app.state.db_pool.acquire.return_value = mock_acquire_ctx
    app.state.supabase_client = AsyncMock()
    
    # with user_id
    resp = client.post(
        "/api/v1/sync/edge-inference",
        headers=auth_headers,
        data={
            "scan_id": str(uuid.uuid4()),
            "patient_id": test_user_id,
            "user_id": test_user_id,
            "scan_type": 1,
            "scan_status": 0,
            "ai_diagnosis": "Normal",
            "confidence": 0.99,
        },
        files={"file": ("test.jpg", b"dummy", "image/jpeg")}
    )
    assert resp.status_code == 422
    assert "Client-supplied user_id and doctor_id form fields are rejected" in resp.json()["detail"]

    # with doctor_id
    resp = client.post(
        "/api/v1/sync/edge-inference",
        headers=auth_headers,
        data={
            "scan_id": str(uuid.uuid4()),
            "patient_id": test_user_id,
            "doctor_id": str(uuid.uuid4()),
            "scan_type": 1,
            "scan_status": 0,
            "ai_diagnosis": "Normal",
            "confidence": 0.99,
        },
        files={"file": ("test.jpg", b"dummy", "image/jpeg")}
    )
    assert resp.status_code == 422
    assert "Client-supplied user_id and doctor_id form fields are rejected" in resp.json()["detail"]
