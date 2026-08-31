import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

VALID_UUID = str(uuid.uuid4())
VALID_USER_ID = "ff46e7d4-df9c-406f-be0c-987537a1b8a3"


def _make_pool_mock(fetchrow_return=None):
    """Build a minimal asyncpg pool mock that supports acquire() as async context manager."""
    pool_mock = MagicMock()
    conn_mock = AsyncMock()
    conn_mock.fetchrow.return_value = fetchrow_return
    pool_mock.acquire.return_value.__aenter__.return_value = conn_mock
    pool_mock.acquire.return_value.__aexit__.return_value = AsyncMock(return_value=False)
    return pool_mock, conn_mock


def _valid_form(scan_id=None, modality="cxr"):
    return {
        "scan_id": scan_id or str(uuid.uuid4()),
        "patient_id": VALID_USER_ID,
        "scan_type": 1,
        "scan_status": 2,
        "ai_diagnosis": "Pneumonia",
        "confidence": 0.95,
        "metadata": "{}",
        "modality": modality,
    }


@pytest.fixture
def mock_storage():
    with patch("app.api.sync_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock:
        mock.return_value = ("https://mock.com/image.jpg", f"{VALID_USER_ID}/scan.jpg")
        yield mock


@pytest.fixture
def mock_db_insert():
    with patch("app.api.sync_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock:
        mock.return_value = True
        yield mock


# ---------------------------------------------------------------------------
# Existing tests (kept, updated where the response contract changed)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_edge_inference_valid(mock_storage, mock_db_insert, auth_headers) -> None:
    """Test successful sync of a valid edge inference payload."""
    scan_id = str(uuid.uuid4())
    metadata_payload = {"device_model": "Pixel 6"}

    pool_mock, conn_mock = _make_pool_mock(fetchrow_return=None)
    app.state.db_pool = pool_mock
    app.state.supabase_client = MagicMock()
    app.state.http_client = MagicMock()

    response = client.post(
        "/api/v1/sync/edge-inference",
        headers=auth_headers,
        data={
            "scan_id": scan_id,
            "patient_id": VALID_USER_ID,
            "scan_type": 1,
            "scan_status": 2,
            "ai_diagnosis": "Pneumonia",
            "confidence": 0.95,
            "metadata": json.dumps(metadata_payload),
            "modality": "cxr",
        },
        files={"file": ("scan.jpg", b"fake_image_data", "image/jpeg")},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "synced"
    assert data["scan_id"] == scan_id
    assert "storage_path" in data
    assert data["storage_path"] == f"{VALID_USER_ID}/scan.jpg"

    mock_storage.assert_called_once()
    mock_db_insert.assert_called_once()

    called_kwargs = mock_db_insert.call_args.kwargs
    assert called_kwargs["metadata"]["inference_source"] == "edge"
    assert called_kwargs["metadata"]["tflite_sync"] is True
    assert called_kwargs["modality"] == "cxr"
    assert called_kwargs["scan_type"] == 1


@pytest.mark.asyncio
async def test_sync_edge_inference_missing_modality_rejected(auth_headers) -> None:
    """Test syncing a scan without modality returns 422."""
    scan_id = str(uuid.uuid4())

    response = client.post(
        "/api/v1/sync/edge-inference",
        headers=auth_headers,
        data={
            "scan_id": scan_id,
            "patient_id": VALID_USER_ID,
            "scan_type": 1,
            "scan_status": 2,
            "ai_diagnosis": "Pneumonia",
            "confidence": 0.95,
            "metadata": "{}",
        },
        files={"file": ("scan.jpg", b"fake_image_data", "image/jpeg")},
    )

    assert response.status_code == 422
    assert "modality" in response.text


@pytest.mark.asyncio
async def test_sync_edge_inference_already_synced(mock_storage, mock_db_insert, auth_headers) -> None:
    """Test syncing a scan that already exists (ON CONFLICT) returns 409."""
    mock_db_insert.return_value = False

    pool_mock, conn_mock = _make_pool_mock(fetchrow_return=None)
    app.state.db_pool = pool_mock
    app.state.supabase_client = MagicMock()
    app.state.http_client = MagicMock()

    scan_id = str(uuid.uuid4())
    response = client.post(
        "/api/v1/sync/edge-inference",
        headers=auth_headers,
        data={
            "scan_id": scan_id,
            "patient_id": VALID_USER_ID,
            "scan_type": 0,
            "scan_status": 0,
            "ai_diagnosis": "Normal",
            "confidence": 0.99,
            "metadata": "{}",
            "modality": "ecg",
        },
        files={"file": ("scan.jpg", b"fake_image_data", "image/jpeg")},
    )

    assert response.status_code == 409, response.text
    data = response.json()
    assert data["status"] == "already_synced"
    assert data["scan_id"] == scan_id
    assert "storage_path" in data


@pytest.mark.asyncio
async def test_sync_edge_inference_user_mismatch(auth_headers) -> None:
    """Test syncing with a user_id different from the JWT sub returns 403."""
    scan_id = str(uuid.uuid4())
    different_user_id = str(uuid.uuid4())

    response = client.post(
        "/api/v1/sync/edge-inference",
        headers=auth_headers,
        data={
            "scan_id": scan_id,
            "patient_id": different_user_id,
            "scan_type": 1,
            "scan_status": 2,
            "ai_diagnosis": "Pneumonia",
            "confidence": 0.95,
            "metadata": "{}",
        },
        files={"file": ("scan.jpg", b"fake_image_data", "image/jpeg")},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_sync_edge_inference_malformed_payload(auth_headers) -> None:
    """Test syncing with malformed UUID returns 422."""
    response = client.post(
        "/api/v1/sync/edge-inference",
        headers=auth_headers,
        data={
            "scan_id": "not-a-uuid",
            "patient_id": VALID_USER_ID,
            "scan_type": 1,
            "scan_status": 2,
            "ai_diagnosis": "Pneumonia",
            "confidence": 0.95,
            "metadata": "{}",
        },
        files={"file": ("scan.jpg", b"fake_image_data", "image/jpeg")},
    )

    assert response.status_code == 422
    assert "not a valid UUID" in response.text or "not-a-uuid" in response.text


@pytest.mark.asyncio
async def test_sync_edge_inference_invalid_scan_type(auth_headers) -> None:
    """Test syncing with out of range scan_type returns 422."""
    scan_id = str(uuid.uuid4())
    response = client.post(
        "/api/v1/sync/edge-inference",
        headers=auth_headers,
        data={
            "scan_id": scan_id,
            "patient_id": VALID_USER_ID,
            "scan_type": 99,
            "scan_status": 2,
            "ai_diagnosis": "Pneumonia",
            "confidence": 0.95,
            "metadata": "{}",
        },
        files={"file": ("scan.jpg", b"fake_image_data", "image/jpeg")},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_scan_type_unchanged_by_modality_write(auth_headers) -> None:
    """Assert scan_type round-trips through every route with its input value untouched."""
    scan_id = str(uuid.uuid4())

    pool_mock, conn_mock = _make_pool_mock(fetchrow_return=None)
    app.state.db_pool = pool_mock
    app.state.supabase_client = MagicMock()
    app.state.http_client = MagicMock()

    with patch("app.api.sync_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.sync_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:
        mock_storage.return_value = ("url", f"{VALID_USER_ID}/path.jpg")
        mock_insert.return_value = True

        response = client.post(
            "/api/v1/sync/edge-inference",
            headers=auth_headers,
            data={
                "scan_id": scan_id,
                "patient_id": VALID_USER_ID,
                "scan_type": 1,
                "scan_status": 2,
                "ai_diagnosis": "Pneumonia",
                "confidence": 0.95,
                "metadata": "{}",
                "modality": "cxr",
            },
            files={"file": ("scan.jpg", b"fake", "image/jpeg")},
        )
        assert response.status_code == 200
        kwargs = mock_insert.call_args[1]
        assert kwargs["scan_type"] == 1


@pytest.mark.asyncio
async def test_sync_modality_form_takes_precedence_over_metadata(auth_headers) -> None:
    scan_id = str(uuid.uuid4())

    pool_mock, conn_mock = _make_pool_mock(fetchrow_return=None)
    app.state.db_pool = pool_mock
    app.state.supabase_client = MagicMock()
    app.state.http_client = MagicMock()

    with patch("app.api.sync_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.sync_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:
        mock_storage.return_value = ("url", f"{VALID_USER_ID}/path.jpg")
        mock_insert.return_value = True

        metadata_payload = json.dumps({"modality": "ecg"})
        response = client.post(
            "/api/v1/sync/edge-inference",
            headers=auth_headers,
            data={
                "scan_id": scan_id,
                "patient_id": VALID_USER_ID,
                "scan_type": 1,
                "scan_status": 2,
                "ai_diagnosis": "Pneumonia",
                "confidence": 0.95,
                "metadata": metadata_payload,
                "modality": "cxr",
            },
            files={"file": ("scan.jpg", b"fake", "image/jpeg")},
        )
        assert response.status_code == 200
        kwargs = mock_insert.call_args[1]
        assert kwargs["modality"] == "cxr"


@pytest.mark.asyncio
async def test_sync_invalid_modality_in_metadata_rejected(auth_headers) -> None:
    scan_id = str(uuid.uuid4())
    metadata_payload = json.dumps({"modality": "xray"})
    response = client.post(
        "/api/v1/sync/edge-inference",
        headers=auth_headers,
        data={
            "scan_id": scan_id,
            "patient_id": VALID_USER_ID,
            "scan_type": 1,
            "scan_status": 2,
            "ai_diagnosis": "Pneumonia",
            "confidence": 0.95,
            "metadata": metadata_payload,
        },
        files={"file": ("scan.jpg", b"fake", "image/jpeg")},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# B26 — required tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_upload_raises_returns_503(auth_headers) -> None:
    """Upload raises → 503, no storage_path in body, insert never called."""
    pool_mock, conn_mock = _make_pool_mock(fetchrow_return=None)
    app.state.db_pool = pool_mock
    app.state.supabase_client = MagicMock()
    app.state.http_client = MagicMock()

    with patch("app.api.sync_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_upload, \
         patch("app.api.sync_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert:
        mock_upload.side_effect = RuntimeError("SDK failure")

        response = client.post(
            "/api/v1/sync/edge-inference",
            headers=auth_headers,
            data=_valid_form(),
            files={"file": ("scan.jpg", b"fake", "image/jpeg")},
        )
        assert response.status_code == 503
        data = response.json()
        assert "storage_path" not in data
        assert data.get("code") == "storage_upload_failed"
        mock_insert.assert_not_called()


@pytest.mark.asyncio
async def test_sync_upload_falsy_path_returns_503(auth_headers) -> None:
    """Upload returns falsy object_path without raising → 503, no storage_path in body, insert never called."""
    pool_mock, conn_mock = _make_pool_mock(fetchrow_return=None)
    app.state.db_pool = pool_mock
    app.state.supabase_client = MagicMock()
    app.state.http_client = MagicMock()

    with patch("app.api.sync_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_upload, \
         patch("app.api.sync_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert:
        # Returns a URL but an empty/falsy object path — SDK returned a bad result without raising.
        mock_upload.return_value = ("https://example.com/obj", "")

        response = client.post(
            "/api/v1/sync/edge-inference",
            headers=auth_headers,
            data=_valid_form(),
            files={"file": ("scan.jpg", b"fake", "image/jpeg")},
        )
        assert response.status_code == 503
        data = response.json()
        assert "storage_path" not in data
        assert data.get("code") == "storage_upload_failed"
        mock_insert.assert_not_called()


@pytest.mark.asyncio
async def test_sync_insert_raises_calls_compensating_delete(auth_headers) -> None:
    """Upload succeeds, insert raises → 503, storage delete called exactly once with the exact uploaded path."""
    pool_mock, conn_mock = _make_pool_mock(fetchrow_return=None)
    app.state.db_pool = pool_mock
    app.state.supabase_client = MagicMock()
    app.state.http_client = MagicMock()

    uploaded_path = f"{VALID_USER_ID}/scan_id.jpg"

    with patch("app.api.sync_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_upload, \
         patch("app.api.sync_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.sync_router.StorageService.delete_scan_objects", new_callable=AsyncMock) as mock_delete:
        mock_upload.return_value = ("https://example.com/img", uploaded_path)
        mock_insert.side_effect = Exception("DB dead")

        response = client.post(
            "/api/v1/sync/edge-inference",
            headers=auth_headers,
            data=_valid_form(),
            files={"file": ("scan.jpg", b"fake", "image/jpeg")},
        )
        assert response.status_code == 503
        data = response.json()
        assert data.get("code") == "sync_write_failed"

        mock_delete.assert_called_once()
        call_kwargs = mock_delete.call_args.kwargs
        assert call_kwargs["object_paths"] == [uploaded_path]
        assert call_kwargs["user_id"] == VALID_USER_ID


@pytest.mark.asyncio
async def test_sync_insert_raises_delete_also_fails_still_503(auth_headers) -> None:
    """Upload succeeds, insert raises, compensating delete also raises → still 503 with sync_write_failed code."""
    pool_mock, conn_mock = _make_pool_mock(fetchrow_return=None)
    app.state.db_pool = pool_mock
    app.state.supabase_client = MagicMock()
    app.state.http_client = MagicMock()

    uploaded_path = f"{VALID_USER_ID}/scan_id.jpg"

    with patch("app.api.sync_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_upload, \
         patch("app.api.sync_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.sync_router.StorageService.delete_scan_objects", new_callable=AsyncMock) as mock_delete:
        mock_upload.return_value = ("https://example.com/img", uploaded_path)
        mock_insert.side_effect = Exception("DB dead")
        mock_delete.side_effect = RuntimeError("Storage cleanup failed")

        response = client.post(
            "/api/v1/sync/edge-inference",
            headers=auth_headers,
            data=_valid_form(),
            files={"file": ("scan.jpg", b"fake", "image/jpeg")},
        )
        assert response.status_code == 503
        assert response.json().get("code") == "sync_write_failed"
        mock_delete.assert_called_once()


@pytest.mark.asyncio
async def test_sync_insert_zero_rows_no_compensating_delete(auth_headers) -> None:
    """Upload succeeds, insert returns zero rows (ON CONFLICT) → 409 already_synced, storage_path present, delete never called."""
    pool_mock, conn_mock = _make_pool_mock(fetchrow_return=None)
    app.state.db_pool = pool_mock
    app.state.supabase_client = MagicMock()
    app.state.http_client = MagicMock()

    uploaded_path = f"{VALID_USER_ID}/scan_id.jpg"
    scan_id = str(uuid.uuid4())

    with patch("app.api.sync_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_upload, \
         patch("app.api.sync_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.sync_router.StorageService.delete_scan_objects", new_callable=AsyncMock) as mock_delete:
        mock_upload.return_value = ("https://example.com/img", uploaded_path)
        mock_insert.return_value = False   # ON CONFLICT fired — zero rows returned

        response = client.post(
            "/api/v1/sync/edge-inference",
            headers=auth_headers,
            data=_valid_form(scan_id=scan_id),
            files={"file": ("scan.jpg", b"fake", "image/jpeg")},
        )
        assert response.status_code == 409
        data = response.json()
        assert data["status"] == "already_synced"
        assert data["storage_path"] == uploaded_path
        mock_delete.assert_not_called()


@pytest.mark.asyncio
async def test_sync_duplicate_scan_id_with_existing_storage_path_skips_upload(auth_headers) -> None:
    """Duplicate scan_id with an existing non-null storage_path → 409 already_synced, upload never called."""
    existing_path = "already/exists.jpg"
    pool_mock, conn_mock = _make_pool_mock(
        fetchrow_return={"scan_id": "test", "storage_path": existing_path, "user_id": VALID_USER_ID}
    )
    app.state.db_pool = pool_mock
    app.state.supabase_client = MagicMock()
    app.state.http_client = MagicMock()

    with patch("app.api.sync_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_upload:
        response = client.post(
            "/api/v1/sync/edge-inference",
            headers=auth_headers,
            data=_valid_form(),
            files={"file": ("scan.jpg", b"fake", "image/jpeg")},
        )
        assert response.status_code == 409
        data = response.json()
        assert data["status"] == "already_synced"
        assert data["storage_path"] == existing_path
        mock_upload.assert_not_called()


@pytest.mark.asyncio
async def test_sync_happy_path_returns_200_with_storage_path(auth_headers) -> None:
    """Happy path → 200 synced, storage_path present, inference_source == 'edge', exactly one upload, zero deletes."""
    uploaded_path = f"{VALID_USER_ID}/scan_id.jpg"
    pool_mock, conn_mock = _make_pool_mock(fetchrow_return=None)
    app.state.db_pool = pool_mock
    app.state.supabase_client = MagicMock()
    app.state.http_client = MagicMock()

    with patch("app.api.sync_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_upload, \
         patch("app.api.sync_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.sync_router.StorageService.delete_scan_objects", new_callable=AsyncMock) as mock_delete:
        mock_upload.return_value = ("https://example.com/object/public/img", uploaded_path)
        mock_insert.return_value = True

        response = client.post(
            "/api/v1/sync/edge-inference",
            headers=auth_headers,
            data=_valid_form(),
            files={"file": ("scan.jpg", b"fake", "image/jpeg")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "synced"
        assert data["storage_path"] == uploaded_path

        insert_kwargs = mock_insert.call_args[1]
        assert insert_kwargs["inference_source"] == "edge"

        mock_upload.assert_called_once()
        mock_insert.assert_called_once()
        mock_delete.assert_not_called()

        assert insert_kwargs["image_url"] == "https://example.com/object/authenticated/img"


@pytest.mark.asyncio
async def test_sync_foreign_row_non_null_path_returns_422(auth_headers) -> None:
    """Pre-check returns a row whose user_id differs from JWT subject with non-null path."""
    foreign_user_id = str(uuid.uuid4())
    pool_mock, conn_mock = _make_pool_mock(
        fetchrow_return={"scan_id": "test", "storage_path": "path", "user_id": foreign_user_id}
    )
    app.state.db_pool = pool_mock
    app.state.supabase_client = MagicMock()
    app.state.http_client = MagicMock()

    with patch("app.api.sync_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_upload:
        response = client.post(
            "/api/v1/sync/edge-inference",
            headers=auth_headers,
            data=_valid_form(),
            files={"file": ("scan.jpg", b"fake", "image/jpeg")},
        )
        assert response.status_code == 422
        data = response.json()
        assert data["code"] == "scan_id_conflict"
        assert "storage_path" not in data
        assert foreign_user_id not in response.text
        assert "path" not in response.text
        mock_upload.assert_not_called()


@pytest.mark.asyncio
async def test_sync_foreign_row_null_path_returns_422(auth_headers) -> None:
    """Pre-check returns a row whose user_id differs from JWT subject with null path."""
    foreign_user_id = str(uuid.uuid4())
    pool_mock, conn_mock = _make_pool_mock(
        fetchrow_return={"scan_id": "test", "storage_path": None, "user_id": foreign_user_id}
    )
    app.state.db_pool = pool_mock
    app.state.supabase_client = MagicMock()
    app.state.http_client = MagicMock()

    with patch("app.api.sync_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_upload:
        response = client.post(
            "/api/v1/sync/edge-inference",
            headers=auth_headers,
            data=_valid_form(),
            files={"file": ("scan.jpg", b"fake", "image/jpeg")},
        )
        assert response.status_code == 422
        data = response.json()
        assert data["code"] == "scan_id_conflict"
        assert "storage_path" not in data
        assert foreign_user_id not in response.text
        mock_upload.assert_not_called()


@pytest.mark.asyncio
async def test_sync_own_row_null_path_updates(auth_headers) -> None:
    """Own row with null storage_path continues to UPDATE path with user_id predicate."""
    pool_mock, conn_mock = _make_pool_mock(
        fetchrow_return={"scan_id": "test", "storage_path": None, "user_id": VALID_USER_ID}
    )
    app.state.db_pool = pool_mock
    app.state.supabase_client = MagicMock()
    app.state.http_client = MagicMock()

    with patch("app.api.sync_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_upload:
        mock_upload.return_value = ("https://example.com/object/public/img", "path")
        response = client.post(
            "/api/v1/sync/edge-inference",
            headers=auth_headers,
            data=_valid_form(),
            files={"file": ("scan.jpg", b"fake", "image/jpeg")},
        )
        assert response.status_code == 409
        data = response.json()
        assert data["status"] == "already_synced"
        assert data["storage_path"] == "path"
        
        # Second call to fetchrow is the UPDATE
        assert conn_mock.fetchrow.call_count == 2
        update_query = conn_mock.fetchrow.call_args_list[1].args[0]
        assert "UPDATE scan_results" in update_query
        assert "user_id = $4::uuid" in update_query


@pytest.mark.asyncio
async def test_sync_insert_zero_rows_foreign_conflict_deletes(auth_headers) -> None:
    """Zero-row insert, conflicting row owned by another user → 422 and compensating delete."""
    uploaded_path = f"{VALID_USER_ID}/scan_id.jpg"
    scan_id = str(uuid.uuid4())

    pool_mock = MagicMock()
    conn_mock = AsyncMock()
    # First fetchrow is pre-check (returns None)
    # Second fetchrow is conflicting row check (returns foreign user)
    conn_mock.fetchrow.side_effect = [
        None,
        {"scan_id": scan_id, "storage_path": "other_path", "user_id": str(uuid.uuid4())}
    ]
    pool_mock.acquire.return_value.__aenter__.return_value = conn_mock
    pool_mock.acquire.return_value.__aexit__.return_value = AsyncMock(return_value=False)
    
    app.state.db_pool = pool_mock
    app.state.supabase_client = MagicMock()
    app.state.http_client = MagicMock()

    with patch("app.api.sync_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_upload, \
         patch("app.api.sync_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.sync_router.StorageService.delete_scan_objects", new_callable=AsyncMock) as mock_delete:
        mock_upload.return_value = ("https://example.com/object/public/img", uploaded_path)
        mock_insert.return_value = False   # ON CONFLICT fired — zero rows returned

        response = client.post(
            "/api/v1/sync/edge-inference",
            headers=auth_headers,
            data=_valid_form(scan_id=scan_id),
            files={"file": ("scan.jpg", b"fake", "image/jpeg")},
        )
        assert response.status_code == 422
        assert response.json()["code"] == "scan_id_conflict"
        from app.core.config import gateway_config
        mock_delete.assert_called_once_with(
            supabase_client=app.state.supabase_client,
            bucket=gateway_config.supabase_storage_bucket,
            user_id=VALID_USER_ID,
            object_paths=[uploaded_path],
        )


@pytest.mark.asyncio
async def test_sync_insert_zero_rows_own_conflict_no_delete(auth_headers) -> None:
    """Zero-row insert, conflicting row owned by caller → 409, no delete."""
    uploaded_path = f"{VALID_USER_ID}/scan_id.jpg"
    scan_id = str(uuid.uuid4())

    pool_mock = MagicMock()
    conn_mock = AsyncMock()
    # First fetchrow is pre-check (returns None)
    # Second fetchrow is conflicting row check (returns caller user)
    conn_mock.fetchrow.side_effect = [
        None,
        {"scan_id": scan_id, "storage_path": uploaded_path, "user_id": VALID_USER_ID}
    ]
    pool_mock.acquire.return_value.__aenter__.return_value = conn_mock
    pool_mock.acquire.return_value.__aexit__.return_value = AsyncMock(return_value=False)
    
    app.state.db_pool = pool_mock
    app.state.supabase_client = MagicMock()
    app.state.http_client = MagicMock()

    with patch("app.api.sync_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_upload, \
         patch("app.api.sync_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.sync_router.StorageService.delete_scan_objects", new_callable=AsyncMock) as mock_delete:
        mock_upload.return_value = ("https://example.com/object/public/img", uploaded_path)
        mock_insert.return_value = False   # ON CONFLICT fired — zero rows returned

        response = client.post(
            "/api/v1/sync/edge-inference",
            headers=auth_headers,
            data=_valid_form(scan_id=scan_id),
            files={"file": ("scan.jpg", b"fake", "image/jpeg")},
        )
        assert response.status_code == 409
        data = response.json()
        assert data["status"] == "already_synced"
        assert data["storage_path"] == uploaded_path
        mock_delete.assert_not_called()


# ---------------------------------------------------------------------------
# Task 1 — xai_status='skipped_edge' test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_edge_sync_insert_passes_skipped_edge_xai_status(auth_headers) -> None:
    """Edge sync insert must pass xai_status='skipped_edge' and xai_path=None explicitly."""
    uploaded_path = f"{VALID_USER_ID}/scan_id.jpg"
    pool_mock, conn_mock = _make_pool_mock(fetchrow_return=None)
    app.state.db_pool = pool_mock
    app.state.supabase_client = MagicMock()
    app.state.http_client = MagicMock()

    with patch("app.api.sync_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_upload, \
         patch("app.api.sync_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.sync_router.StorageService.delete_scan_objects", new_callable=AsyncMock):
        mock_upload.return_value = ("https://example.com/object/public/img", uploaded_path)
        mock_insert.return_value = True

        response = client.post(
            "/api/v1/sync/edge-inference",
            headers=auth_headers,
            data=_valid_form(),
            files={"file": ("scan.jpg", b"fake", "image/jpeg")},
        )
        assert response.status_code == 200

        insert_kwargs = mock_insert.call_args[1]
        assert insert_kwargs["xai_status"] == "skipped_edge"
        assert insert_kwargs.get("xai_path") is None
