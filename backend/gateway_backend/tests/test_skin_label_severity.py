"""Tests for skin label severity mapping and unknown-label rejection.

Covers:
- derive_scan_status parametrized over every skin model class (Fix 1 + Fix 2).
- Unknown labels for skin, cxr, ecg raise HTTP 500; nothing is persisted.
- Label set equality: the skin normal+abnormal union must match the model's exact class list.

#z8v0kmrkv4  ClickUp B54
"""
import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from httpx import Response

from app.main import app
from app.services.scan_persistence_service import ScanPersistenceService
from app.utils.labels import _NORMAL_LABELS, _ABNORMAL_LABELS

client = TestClient(app)

# ---------------------------------------------------------------------------
# Ground-truth class list for the skin model (all 8 classes, exact spelling).
# Source: skin_service/src/app/core/config.py skin_labels + "Normal skin" (new class).
# The union of _NORMAL_LABELS["skin"] | _ABNORMAL_LABELS["skin"] MUST equal this set.
# ---------------------------------------------------------------------------
_SKIN_MODEL_CLASSES = {
    "Normal skin",
    "Actinic keratoses",
    "Basal cell carcinoma",
    "Benign keratosis-like lesions",
    "Dermatofibroma",
    "Melanocytic nevi",
    "Melanoma",
    "Vascular lesions",
}


# ---------------------------------------------------------------------------
# FIX 1 — Label set integrity
# ---------------------------------------------------------------------------

class TestSkinLabelSets:
    """The union of normal + abnormal skin labels must exactly equal the model's class list."""

    def test_normal_skin_label_set_exact(self):
        assert _NORMAL_LABELS["skin"] == {"Normal skin"}, (
            "Normal skin label set drifted from model output."
        )

    def test_abnormal_skin_label_set_exact(self):
        assert _ABNORMAL_LABELS["skin"] == {
            "Actinic keratoses",
            "Basal cell carcinoma",
            "Benign keratosis-like lesions",
            "Dermatofibroma",
            "Melanocytic nevi",
            "Melanoma",
            "Vascular lesions",
        }, "Abnormal skin label set drifted from model output."

    def test_skin_label_union_equals_model_classes(self):
        """Union of both sets must exactly equal the model's class list — no missing, no extras."""
        union = _NORMAL_LABELS["skin"] | _ABNORMAL_LABELS["skin"]
        assert union == _SKIN_MODEL_CLASSES, (
            f"Label union {union!r} does not match model classes {_SKIN_MODEL_CLASSES!r}"
        )

    def test_normal_and_abnormal_are_disjoint(self):
        """No label should appear in both sets."""
        overlap = _NORMAL_LABELS["skin"] & _ABNORMAL_LABELS["skin"]
        assert overlap == set(), f"Labels appear in both sets: {overlap!r}"

    def test_basal_cell_carcinoma_is_in_abnormal(self):
        """Regression guard: BCC was missing from abnormal set before this fix."""
        assert "Basal cell carcinoma" in _ABNORMAL_LABELS["skin"]

    def test_dermatofibroma_is_in_abnormal(self):
        """Regression guard: Dermatofibroma was wrongly classified as normal before this fix."""
        assert "Dermatofibroma" in _ABNORMAL_LABELS["skin"]

    def test_normal_skin_not_in_abnormal(self):
        assert "Normal skin" not in _ABNORMAL_LABELS["skin"]


# ---------------------------------------------------------------------------
# FIX 1+2 — derive_scan_status parametrized over every skin class
# ---------------------------------------------------------------------------

# Classes that should resolve to status 0 (Normal/healthy)
SKIN_NORMAL_CLASSES = [
    pytest.param("Normal skin", id="Normal_skin"),
]

# Classes that should resolve to non-zero (1 or 2) — at confidence >= 0.85 -> status 2
SKIN_ABNORMAL_CLASSES = [
    pytest.param("Actinic keratoses",         id="Actinic_keratoses"),
    pytest.param("Basal cell carcinoma",      id="Basal_cell_carcinoma"),
    pytest.param("Benign keratosis-like lesions", id="Benign_keratosis"),
    pytest.param("Dermatofibroma",            id="Dermatofibroma"),
    pytest.param("Melanocytic nevi",          id="Melanocytic_nevi"),
    pytest.param("Melanoma",                  id="Melanoma"),
    pytest.param("Vascular lesions",          id="Vascular_lesions"),
]


@pytest.mark.parametrize("label", SKIN_NORMAL_CLASSES)
def test_skin_normal_class_yields_status_0(label):
    """Every skin normal class must produce scan_status=0 regardless of confidence."""
    status = ScanPersistenceService.derive_scan_status(0.99, ai_diagnosis=label, modality="skin")
    assert status == 0, f"Expected 0 for '{label}', got {status}"


@pytest.mark.parametrize("label", SKIN_ABNORMAL_CLASSES)
def test_skin_abnormal_class_high_confidence_yields_status_2(label):
    """Every skin abnormal class at >= 0.85 confidence must produce scan_status=2."""
    status = ScanPersistenceService.derive_scan_status(0.90, ai_diagnosis=label, modality="skin")
    assert status != 0, f"Expected non-zero for '{label}', got {status}"
    assert status == 2, f"Expected 2 for '{label}' at high confidence, got {status}"


@pytest.mark.parametrize("label", SKIN_ABNORMAL_CLASSES)
def test_skin_abnormal_class_warning_confidence_yields_status_1(label):
    """Every skin abnormal class at [0.50, 0.85) confidence must produce scan_status=1."""
    status = ScanPersistenceService.derive_scan_status(0.70, ai_diagnosis=label, modality="skin")
    assert status == 1, f"Expected 1 for '{label}' at warning confidence, got {status}"


def test_skin_basal_cell_carcinoma_high_risk():
    """Explicit regression: BCC at high confidence must be status 2."""
    status = ScanPersistenceService.derive_scan_status(
        0.91, ai_diagnosis="Basal cell carcinoma", modality="skin"
    )
    assert status == 2


def test_skin_dermatofibroma_warning():
    """Explicit regression: Dermatofibroma at warning confidence must be status 1 (not 0)."""
    status = ScanPersistenceService.derive_scan_status(
        0.70, ai_diagnosis="Dermatofibroma", modality="skin"
    )
    assert status == 1


# ---------------------------------------------------------------------------
# FIX 2 — Unknown labels must raise, not silently return 0 or 1
# ---------------------------------------------------------------------------

class TestUnknownLabelRejection:
    """Unrecognised labels must raise HTTP 500 for all modalities."""

    def test_unknown_skin_label_raises(self):
        with pytest.raises(HTTPException) as exc_info:
            ScanPersistenceService.derive_scan_status(
                0.99, ai_diagnosis="Unknown Skin Disease", modality="skin"
            )
        assert exc_info.value.status_code == 500
        assert "skin" in exc_info.value.detail
        assert "Unknown Skin Disease" in exc_info.value.detail

    def test_unknown_cxr_label_raises(self):
        with pytest.raises(HTTPException) as exc_info:
            ScanPersistenceService.derive_scan_status(
                0.99, ai_diagnosis="Totally Unknown CXR Finding", modality="cxr"
            )
        assert exc_info.value.status_code == 500
        assert "cxr" in exc_info.value.detail
        assert "Totally Unknown CXR Finding" in exc_info.value.detail

    def test_unknown_ecg_label_raises(self):
        with pytest.raises(HTTPException) as exc_info:
            ScanPersistenceService.derive_scan_status(
                0.99, ai_diagnosis="Strange ECG Pattern", modality="ecg"
            )
        assert exc_info.value.status_code == 500
        assert "ecg" in exc_info.value.detail
        assert "Strange ECG Pattern" in exc_info.value.detail

    def test_unknown_label_does_not_persist_via_skin_router(auth_headers):
        """When derive_scan_status raises, insert_scan_result must NOT be called."""
        mock_ml_client = AsyncMock()
        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "predicted_class": "Completely Unknown Skin Label",
            "top_findings": [{"label": "Completely Unknown Skin Label", "confidence": 0.95}],
        }
        mock_response.raise_for_status = MagicMock()
        mock_ml_client.post.return_value = mock_response
        app.state.http_client = mock_ml_client
        app.state.db_pool = MagicMock()
        app.state.supabase_client = MagicMock()

        with patch(
            "app.api.skin_router.ScanPersistenceService.insert_scan_result",
            new_callable=AsyncMock,
        ) as mock_insert, patch(
            "app.api.skin_router.StorageService.upload_scan_image",
            new_callable=AsyncMock,
        ) as mock_storage:
            mock_storage.return_value = ("url", "path")
            from tests.conftest import PRIVATE_PEM
            from jose import jwt
            import time
            claims = {
                "sub": "ff46e7d4-df9c-406f-be0c-987537a1b8a3",
                "role": "authenticated",
                "aud": "authenticated",
                "iss": "https://ppwnixwhaxpsqvufdggy.supabase.co/auth/v1",
                "exp": int(time.time()) + 3600,
            }
            token = jwt.encode(claims, PRIVATE_PEM, algorithm="ES256", headers={"kid": "test-kid"})
            hdrs = {"Authorization": f"Bearer {token}"}
            response = client.post(
                "/api/v1/skin/predict",
                headers=hdrs,
                files={"file": ("skin.jpg", b"data", "image/jpeg")},
            )
            # Must not have persisted anything
            mock_insert.assert_not_awaited()
            # The endpoint should propagate the 500
            assert response.status_code == 500


# ---------------------------------------------------------------------------
# Existing CXR / ECG derive_scan_status tests must still pass (unchanged)
# ---------------------------------------------------------------------------

def test_existing_normal_cxr():
    assert ScanPersistenceService.derive_scan_status(0.99, ai_diagnosis="No Finding", modality="cxr") == 0


def test_existing_abnormal_ecg_high_risk():
    assert ScanPersistenceService.derive_scan_status(0.90, ai_diagnosis="MI", modality="ecg") == 2
