import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.security import get_current_user

client = TestClient(app)

VALID_UUID = str(uuid.uuid4())
VALID_USER_ID = str(uuid.uuid4())

@pytest.fixture
def mock_storage():
    with patch("app.api.sync_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock:
        mock.return_value = "https://mock-storage.com/image.jpg"
        yield mock

@pytest.fixture
def mock_db_insert():
    with patch("app.api.sync_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock:
        mock.return_value = True
        yield mock

@pytest.fixture
def auth_override():
    app.dependency_overrides[get_current_user] = lambda: VALID_USER_ID
    yield
    app.dependency_overrides.pop(get_current_user, None)

@pytest.mark.asyncio
async def test_sync_edge_inference_valid(mock_storage, mock_db_insert, auth_override) -> None:
    """Test successful sync of a valid edge inference payload."""
    scan_id = str(uuid.uuid4())
    metadata_payload = {"device_model": "Pixel 6"}
    
    # We need app.state.db_pool to not be None
    app.state.db_pool = AsyncMock()
    app.state.supabase_client = AsyncMock()
    app.state.http_client = AsyncMock()
    
    response = client.post(
        "/api/v1/sync/edge-inference",
        data={
            "scan_id": scan_id,
            "user_id": VALID_USER_ID,
            "scan_type": 1,
            "scan_status": 2,
            "ai_diagnosis": "Pneumonia",
            "confidence": 0.95,
            "metadata": json.dumps(metadata_payload)
        },
        files={"file": ("scan.jpg", b"fake_image_data", "image/jpeg")}
    )
    
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "synced"
    assert data["scan_id"] == scan_id
    assert data["image_url"] == "https://mock-storage.com/image.jpg"
    
    mock_storage.assert_called_once()
    mock_db_insert.assert_called_once()
    
    # Verify the inserted metadata has been annotated
    called_kwargs = mock_db_insert.call_args.kwargs
    assert called_kwargs["metadata"]["inference_source"] == "edge"
    assert called_kwargs["metadata"]["tflite_sync"] is True

@pytest.mark.asyncio
async def test_sync_edge_inference_already_synced(mock_storage, mock_db_insert, auth_override) -> None:
    """Test syncing a scan that already exists returns 409."""
    mock_db_insert.return_value = False
    app.state.db_pool = AsyncMock()
    app.state.supabase_client = AsyncMock()
    app.state.http_client = AsyncMock()
    
    scan_id = str(uuid.uuid4())
    response = client.post(
        "/api/v1/sync/edge-inference",
        data={
            "scan_id": scan_id,
            "user_id": VALID_USER_ID,
            "scan_type": 0,
            "scan_status": 0,
            "ai_diagnosis": "Normal",
            "confidence": 0.99,
            "metadata": "{}"
        },
        files={"file": ("scan.jpg", b"fake_image_data", "image/jpeg")}
    )
    
    assert response.status_code == 409, response.text
    data = response.json()
    assert data["status"] == "already_synced"
    assert data["scan_id"] == scan_id

@pytest.mark.asyncio
async def test_sync_edge_inference_user_mismatch(auth_override) -> None:
    """Test syncing with a user_id different from the JWT sub returns 403."""
    scan_id = str(uuid.uuid4())
    different_user_id = str(uuid.uuid4())
    
    response = client.post(
        "/api/v1/sync/edge-inference",
        data={
            "scan_id": scan_id,
            "user_id": different_user_id,
            "scan_type": 1,
            "scan_status": 2,
            "ai_diagnosis": "Pneumonia",
            "confidence": 0.95,
            "metadata": "{}"
        },
        files={"file": ("scan.jpg", b"fake_image_data", "image/jpeg")}
    )
    
    assert response.status_code == 403

@pytest.mark.asyncio
async def test_sync_edge_inference_malformed_payload(auth_override) -> None:
    """Test syncing with an invalid scan_type and malformed UUID returns 422."""
    response = client.post(
        "/api/v1/sync/edge-inference",
        data={
            "scan_id": "not-a-uuid",
            "user_id": VALID_USER_ID,
            "scan_type": 1,
            "scan_status": 2,
            "ai_diagnosis": "Pneumonia",
            "confidence": 0.95,
            "metadata": "{}"
        },
        files={"file": ("scan.jpg", b"fake_image_data", "image/jpeg")}
    )
    
    assert response.status_code == 422
    assert "not a valid UUID" in response.text or "not-a-uuid" in response.text

@pytest.mark.asyncio
async def test_sync_edge_inference_invalid_scan_type(auth_override) -> None:
    """Test syncing with out of range scan_type returns 422."""
    scan_id = str(uuid.uuid4())
    response = client.post(
        "/api/v1/sync/edge-inference",
        data={
            "scan_id": scan_id,
            "user_id": VALID_USER_ID,
            "scan_type": 99,
            "scan_status": 2,
            "ai_diagnosis": "Pneumonia",
            "confidence": 0.95,
            "metadata": "{}"
        },
        files={"file": ("scan.jpg", b"fake_image_data", "image/jpeg")}
    )
    
    assert response.status_code == 422
