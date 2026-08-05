"""Tests for Task 4 — explainability in modality router responses and CXR metadata cleanup."""

import base64
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import Response
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import gateway_config

client = TestClient(app)

VALID_USER_ID = "ff46e7d4-df9c-406f-be0c-987537a1b8a3"


# ---------------------------------------------------------------------------
# CXR metadata no longer contains "xai" key
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cxr_persisted_metadata_absent_xai_key(auth_headers) -> None:
    """After Task 1: persisted metadata must not contain an 'xai' key."""
    import base64 as b64
    fake_b64 = b64.b64encode(b"overlay_bytes").decode()
    fake_ml = {
        "predicted_diagnoses": ["Pneumonia"],
        "original_img": fake_b64,
        "top_findings": [
            {"label": "Infiltrate", "confidence": 0.90, "class_idx": 4, "abbreviation": "INF", "overlay_img": fake_b64}
        ],
    }

    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = fake_ml
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()

    with patch("app.api.cxr_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock) as mock_insert, \
         patch("app.api.cxr_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:
        mock_storage.side_effect = [("url_o", "path_o"), ("url_m", "path_m")]
        client.post(
            "/api/v1/cxr/predict",
            headers=auth_headers,
            files={"file": ("xray.jpg", b"data", "image/jpeg")},
        )

        metadata = mock_insert.call_args[1]["metadata"]
        assert "xai" not in metadata


# ---------------------------------------------------------------------------
# CXR explainability in response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cxr_response_includes_explainability_generated(auth_headers) -> None:
    """CXR router returns explainability with status='generated' and non-null url when overlays uploaded."""
    import base64 as b64
    fake_b64 = b64.b64encode(b"overlay_bytes").decode()
    fake_ml = {
        "predicted_diagnoses": ["Pneumonia"],
        "top_findings": [
            {"label": "Infiltrate", "confidence": 0.90, "class_idx": 4, "abbreviation": "INF", "overlay_img": fake_b64}
        ],
    }

    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = fake_ml
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()

    with patch("app.api.cxr_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock), \
         patch("app.api.cxr_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:
        mock_storage.side_effect = [
            ("url_o", f"{VALID_USER_ID}/scan/overlay_0.png"),
            ("url_m", f"{VALID_USER_ID}/scan.jpg"),
        ]

        resp = client.post(
            "/api/v1/cxr/predict",
            headers=auth_headers,
            files={"file": ("xray.jpg", b"data", "image/jpeg")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "explainability" in data
    xai = data["explainability"]
    assert xai["status"] == "generated"
    assert xai["url"] is not None
    assert "/authenticated/" in xai["url"]
    assert "/public/" not in xai["url"]
    assert "?" not in xai["url"]
    assert xai["modality"] == "cxr"


@pytest.mark.asyncio
async def test_cxr_response_explainability_none_when_no_overlays(auth_headers) -> None:
    """CXR router returns status='none' and url=null when no overlays exist."""
    fake_ml = {
        "predicted_diagnoses": ["Normal"],
        "top_findings": [{"label": "Normal", "confidence": 0.99, "class_idx": 0}],
    }

    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = fake_ml
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()

    with patch("app.api.cxr_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock), \
         patch("app.api.cxr_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:
        mock_storage.return_value = ("url_m", "path_m")

        resp = client.post(
            "/api/v1/cxr/predict",
            headers=auth_headers,
            files={"file": ("xray.jpg", b"data", "image/jpeg")},
        )

    assert resp.status_code == 200
    xai = resp.json()["explainability"]
    assert xai["status"] == "none"
    assert xai["url"] is None
    assert xai["modality"] == "cxr"


# ---------------------------------------------------------------------------
# ECG explainability in response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ecg_response_includes_explainability(auth_headers) -> None:
    """ECG router returns explainability with status='none' and url=null."""
    fake_ml = {"predicted_class": "Normal Sinus Rhythm", "confidence": 0.95}

    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = fake_ml
    mock_response.raise_for_status = MagicMock()
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()

    with patch("app.api.ecg_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock), \
         patch("app.api.ecg_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:
        mock_storage.return_value = ("url_m", "path_m")

        resp = client.post(
            "/api/v1/ecg/predict",
            headers=auth_headers,
            files={"file": ("ecg.csv", b"data", "application/octet-stream")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "explainability" in data
    xai = data["explainability"]
    assert xai["status"] == "none"
    assert xai["url"] is None
    assert xai["modality"] == "ecg"


# ---------------------------------------------------------------------------
# Skin explainability in response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_skin_response_includes_explainability_generated(auth_headers) -> None:
    """Skin router returns explainability with status='generated' and non-null url when overlays uploaded."""
    fake_b64 = base64.b64encode(b"overlay_bytes").decode()
    fake_ml = {
        "predicted_class": "Melanoma",
        "top_findings": [
            {"label": "Melanoma", "confidence": 0.91, "class_idx": 0, "abbreviation": "mel", "overlay_img": fake_b64}
        ],
    }

    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = fake_ml
    mock_response.raise_for_status = MagicMock()
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()

    with patch("app.api.skin_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock), \
         patch("app.api.skin_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:
        mock_storage.side_effect = [
            ("url_o", f"{VALID_USER_ID}/scan/overlay_0.png"),
            ("url_m", f"{VALID_USER_ID}/scan.jpg"),
        ]

        resp = client.post(
            "/api/v1/skin/predict",
            headers=auth_headers,
            files={"file": ("skin.jpg", b"data", "image/jpeg")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "explainability" in data
    xai = data["explainability"]
    assert xai["status"] == "generated"
    assert xai["url"] is not None
    assert "/authenticated/" in xai["url"]
    assert "/public/" not in xai["url"]
    assert "?" not in xai["url"]
    assert xai["modality"] == "skin"


@pytest.mark.asyncio
async def test_skin_response_explainability_failed_url_null(auth_headers) -> None:
    """Skin router returns status='failed' and url=null when overlay upload fails."""
    fake_b64 = base64.b64encode(b"overlay_bytes").decode()
    fake_ml = {
        "predicted_class": "Melanoma",
        "top_findings": [
            {"label": "Melanoma", "confidence": 0.91, "class_idx": 0, "abbreviation": "mel", "overlay_img": fake_b64}
        ],
    }

    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = fake_ml
    mock_response.raise_for_status = MagicMock()
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    app.state.db_pool = MagicMock()
    app.state.supabase_client = MagicMock()

    with patch("app.api.skin_router.ScanPersistenceService.insert_scan_result", new_callable=AsyncMock), \
         patch("app.api.skin_router.StorageService.upload_scan_image", new_callable=AsyncMock) as mock_storage:

        def storage_effect(*args, **kwargs):
            if "overlay" in kwargs.get("object_path", ""):
                raise RuntimeError("overlay upload failed")
            return ("url_m", "path_m")

        mock_storage.side_effect = storage_effect

        resp = client.post(
            "/api/v1/skin/predict",
            headers=auth_headers,
            files={"file": ("skin.jpg", b"data", "image/jpeg")},
        )

    assert resp.status_code == 200
    xai = resp.json()["explainability"]
    assert xai["status"] == "failed"
    assert xai["url"] is None
    assert xai["modality"] == "skin"
