"""Tests for the Gateway API skin router — XAI handling and modality persistence."""

import base64
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import Response, HTTPStatusError, Request as HttpxRequest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import gateway_config

client = TestClient(app)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_b64():
    """A minimal valid base64-encoded PNG blob."""
    return base64.b64encode(b"fake_skin_overlay_image_data_1234567890").decode("utf-8")


@pytest.fixture
def fake_ml_data(fake_b64):
    """Skin ML response shape: original_img + top_findings with overlay_img."""
    return {
        "original_img": fake_b64,
        "top_findings": [
            {
                "label": "Melanoma",
                "abbreviation": "mel",
                "class_idx": 0,
                "confidence": 0.91,
                "overlay_img": fake_b64,
            },
            {
                "label": "Melanocytic nevi",
                "abbreviation": "nv",
                "class_idx": 1,
                "confidence": 0.07,
                "overlay_img": fake_b64,
            },
        ],
        "predicted_class": "Melanoma",
        "patient_id": "skin.jpg",
    }


# ---------------------------------------------------------------------------
# Existing tests (unchanged)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_skin_predict_valid_input(auth_headers):
    """Test valid-input inference: it should return the expected response shape."""
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "predicted_class": "Melanoma",
        "top_findings": [{"confidence": 0.89}],
        "findings": "Malignant",
    }
    mock_response.raise_for_status = MagicMock()
    mock_client.post.return_value = mock_response

    app.state.http_client = mock_client
    app.state.db_pool = None
    response = client.post(
        "/api/v1/skin/predict",
        files={"file": ("skin.jpg", b"fake_skin_data", "image/jpeg")},
        data={"top_k": 3},
        headers=auth_headers,
    )
    assert mock_client.post.called
    assert response.status_code == 200
    assert response.json() == {
        "predicted_class": "Melanoma",
        "top_findings": [{"confidence": 0.89}],
        "findings": "Malignant",
    }

    call_args = mock_client.post.call_args
    url = call_args.args[0]
    assert url == f"{gateway_config.skin_service_url}/predict"
    assert "file" in call_args.kwargs["files"]
    assert call_args.kwargs["files"]["file"][1] == b"fake_skin_data"
    assert call_args.kwargs["data"]["top_k"] == "3" or call_args.kwargs["data"]["top_k"] == 3


@pytest.mark.asyncio
async def test_skin_predict_missing_file(auth_headers):
    """Test malformed/missing input: it should return the right 4xx status."""
    response = client.post(
        "/api/v1/skin/predict",
        data={"top_k": 3},
        headers=auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_skin_predict_too_large(auth_headers):
    """Test malformed/missing input: it should return the right 4xx status."""
    oversized = b"x" * (gateway_config.max_upload_bytes + 1)
    response = client.post(
        "/api/v1/skin/predict",
        files={"file": ("huge.jpg", oversized, "image/jpeg")},
        data={"top_k": 1},
        headers=auth_headers,
    )
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_skin_predict_upstream_error(auth_headers):
    """Test that a raised inference error is handled."""
    mock_client = AsyncMock()

    req = HttpxRequest("POST", f"{gateway_config.skin_service_url}/predict")
    mock_response = Response(status_code=500, request=req)

    mock_client.post.side_effect = HTTPStatusError(
        "Internal Server Error",
        request=req,
        response=mock_response,
    )

    app.state.http_client = mock_client
    response = client.post(
        "/api/v1/skin/predict",
        files={"file": ("skin.jpg", b"fake", "image/jpeg")},
        data={"top_k": 3},
        headers=auth_headers,
    )
    assert response.status_code == 503
    data = response.json()
    assert data.get("error") is True
    assert data.get("type") == "ServiceUnavailableError"


@pytest.mark.asyncio
async def test_skin_persists_expected_modality(auth_headers) -> None:
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"predictions": []}
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()

    with patch("app.api.skin_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.skin_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:
        mock_storage.return_value = ("url", "path")
        response = client.post(
            "/api/v1/skin/predict",
            headers=auth_headers,
            files={"file": ("skin.jpg", b"data", "image/jpeg")},
        )
        assert response.status_code == 200
        assert mock_insert.called
        kwargs = mock_insert.call_args.kwargs
        assert kwargs["modality"] == "skin"
        assert kwargs["scan_type"] == 2


# ---------------------------------------------------------------------------
# New XAI tests (Task 2)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_skin_overlay_objects_land_in_expected_path(auth_headers, fake_ml_data) -> None:
    """Overlay uploaded to {user_id}/{scan_id}/overlay_0.png; xai_status='generated'; xai_path set."""
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = fake_ml_data
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()

    with patch("app.api.skin_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.skin_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage, \
         patch("app.api.skin_router.StorageService.delete_scan_objects", new_callable=AsyncMock) as mock_delete:

        mock_storage.side_effect = [
            ("url_overlay_0", "user123/scan456/overlay_0.png"),
            ("url_overlay_1", "user123/scan456/overlay_1.png"),
            ("url_main", "user123/scan456.png"),
        ]

        client.post(
            "/api/v1/skin/predict",
            headers=auth_headers,
            files={"file": ("skin.jpg", b"data", "image/jpeg")},
        )

        # First storage call is the index-0 overlay
        first_overlay_call_kwargs = mock_storage.call_args_list[0].kwargs
        insert_kwargs = mock_insert.call_args.kwargs
        expected_user_id = insert_kwargs["user_id"]
        expected_scan_id = insert_kwargs["scan_id"]

        assert first_overlay_call_kwargs["object_path"] == f"{expected_user_id}/{expected_scan_id}/overlay_0.png"
        assert insert_kwargs["xai_status"] == "generated"
        assert insert_kwargs["xai_path"] == "user123/scan456/overlay_0.png"
        assert mock_delete.call_count == 0


@pytest.mark.asyncio
async def test_skin_overlay_upload_failure(auth_headers, fake_ml_data) -> None:
    """Upload failure yields xai_status='failed', xai_path=None, scan still persisted."""
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = fake_ml_data
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()

    with patch("app.api.skin_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.skin_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:

        def storage_side_effect(*args, **kwargs):
            if "overlay" in kwargs.get("object_path", ""):
                raise RuntimeError("Overlay upload failed")
            return ("url_main", "user123/scan456.png")

        mock_storage.side_effect = storage_side_effect

        response = client.post(
            "/api/v1/skin/predict",
            headers=auth_headers,
            files={"file": ("skin.jpg", b"data", "image/jpeg")},
        )

        assert response.status_code == 200
        kwargs = mock_insert.call_args.kwargs
        assert kwargs["xai_status"] == "failed"
        assert kwargs.get("xai_path") is None
        # Scan itself must still be persisted
        assert mock_insert.called


@pytest.mark.asyncio
async def test_skin_no_overlays(auth_headers) -> None:
    """ML result with no overlay_img yields xai_status='none'."""
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "predicted_class": "Normal",
        "top_findings": [{"label": "Normal", "confidence": 0.99, "class_idx": 0}],
    }
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()

    with patch("app.api.skin_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.skin_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:

        mock_storage.return_value = ("url_main", "user123/scan456.png")

        response = client.post(
            "/api/v1/skin/predict",
            headers=auth_headers,
            files={"file": ("skin.jpg", b"data", "image/jpeg")},
        )

        assert response.status_code == 200
        kwargs = mock_insert.call_args.kwargs
        assert kwargs["xai_status"] == "none"
        assert kwargs.get("xai_path") is None


@pytest.mark.asyncio
async def test_skin_original_img_absent_from_metadata(auth_headers, fake_ml_data) -> None:
    """original_img is popped before persistence; must not appear in persisted metadata."""
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = fake_ml_data
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()

    with patch("app.api.skin_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.skin_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:

        mock_storage.side_effect = [
            ("url_o0", "path_o0"),
            ("url_o1", "path_o1"),
            ("url_m", "path_m"),
        ]

        client.post(
            "/api/v1/skin/predict",
            headers=auth_headers,
            files={"file": ("skin.jpg", b"data", "image/jpeg")},
        )

        metadata = mock_insert.call_args.kwargs["metadata"]
        assert "original_img" not in metadata


@pytest.mark.asyncio
async def test_skin_overlay_img_absent_overlay_path_present(auth_headers, fake_ml_data) -> None:
    """overlay_img replaced by overlay_path in persisted top_findings."""
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = fake_ml_data
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()

    with patch("app.api.skin_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.skin_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:

        mock_storage.side_effect = [
            ("url_o0", "path_o0"),
            ("url_o1", "path_o1"),
            ("url_m", "path_m"),
        ]

        client.post(
            "/api/v1/skin/predict",
            headers=auth_headers,
            files={"file": ("skin.jpg", b"data", "image/jpeg")},
        )

        metadata = mock_insert.call_args.kwargs["metadata"]
        assert "overlay_img" not in metadata["top_findings"][0]
        assert "overlay_path" in metadata["top_findings"][0]


@pytest.mark.asyncio
async def test_skin_compensating_delete_on_persistence_failure(auth_headers, fake_ml_data) -> None:
    """Orphaned storage objects deleted when the database insert raises."""
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = fake_ml_data
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()

    with patch("app.api.skin_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.skin_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_upload, \
         patch("app.api.skin_router.StorageService.delete_scan_objects", new_callable=AsyncMock) as mock_delete:

        mock_upload.side_effect = [
            ("url_o0", "user123/scan456/overlay_0.png"),
            ("url_o1", "user123/scan456/overlay_1.png"),
            ("url_m", "user123/scan456.png"),
        ]
        mock_insert.side_effect = RuntimeError("Database is down")

        with pytest.raises(RuntimeError, match="Database is down"):
            client.post(
                "/api/v1/skin/predict",
                headers=auth_headers,
                files={"file": ("skin.jpg", b"data", "image/jpeg")},
            )

        assert mock_delete.call_count == 1
        deleted_paths = mock_delete.call_args.kwargs["object_paths"]
        assert "user123/scan456/overlay_0.png" in deleted_paths
        assert "user123/scan456/overlay_1.png" in deleted_paths


@pytest.mark.asyncio
async def test_skin_metadata_size_bounded(auth_headers, fake_ml_data) -> None:
    """Persisted metadata must not contain large base64 blobs — bounded to < 4096 bytes."""
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = fake_ml_data
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()

    with patch("app.api.skin_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.skin_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:

        mock_storage.side_effect = [
            ("url_o0", "path_o0"),
            ("url_o1", "path_o1"),
            ("url_m", "path_m"),
        ]

        client.post(
            "/api/v1/skin/predict",
            headers=auth_headers,
            files={"file": ("skin.jpg", b"data", "image/jpeg")},
        )

        metadata = mock_insert.call_args.kwargs["metadata"]
        metadata_str = json.dumps(metadata)
        assert len(metadata_str) < 4096
