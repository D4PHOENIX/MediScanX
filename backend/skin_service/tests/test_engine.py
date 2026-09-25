"""Tests for the Skin Lesion Inference Service engine, preprocessor, and triage."""

import numpy as np
import pytest
import torch
from PIL import Image


def test_preprocessor_corrupt_image(tmp_path) -> None:
    """Assert preprocessor raises UnreadableImageFormatError on corrupt image."""
    from app.engine.preprocessor import SkinPreprocessor
    from app.core.config import SkinInferenceConfig
    from app.core.exceptions import UnreadableImageFormatError

    cfg = SkinInferenceConfig()
    preprocessor = SkinPreprocessor(cfg)

    corrupt_image = tmp_path / "corrupt.jpg"
    corrupt_image.write_bytes(b"not an image")

    with pytest.raises(UnreadableImageFormatError):
        preprocessor.process(str(corrupt_image))


def test_efficientnet_b0_architecture() -> None:
    """Assert EfficientNetB0Classifier outputs 8 class logits for 224x224 input."""
    from app.models.efficientnet_b0 import EfficientNetB0Classifier

    model = EfficientNetB0Classifier(num_classes=8)
    model.eval()

    dummy_tensor = torch.randn(1, 3, 224, 224)
    with torch.no_grad():
        out = model(dummy_tensor)

    assert out.shape == (1, 8)


def test_melanoma_triage_threshold_guard() -> None:
    """Assert melanoma probability >= 0.20 triggers URGENT_REFERRAL even when not top-1."""
    from app.engine.diagnostic_engine import SkinDiagnosticEngine
    from app.core.config import SkinInferenceConfig
    from unittest.mock import MagicMock

    cfg = SkinInferenceConfig()
    engine = SkinDiagnosticEngine(cfg, MagicMock(), MagicMock(), MagicMock())

    # Simulated distribution where benign nv is top-1 (0.60), but melanoma is 0.25 (>= 0.20)
    # class abbreviations: ['akiec', 'bcc', 'bkl', 'df', 'mel', 'normal', 'nv', 'vasc']
    probs = np.array([0.02, 0.03, 0.05, 0.02, 0.25, 0.01, 0.60, 0.02], dtype=np.float32)

    triage, alert, note = engine.determine_triage(probs, top_pred_idx=6)
    assert triage == "URGENT_REFERRAL"
    assert alert is True
    assert "High-risk melanoma" in note


def test_normal_skin_triage_healthy() -> None:
    """Assert top prediction of normal skin returns HEALTHY_SKIN triage."""
    from app.engine.diagnostic_engine import SkinDiagnosticEngine
    from app.core.config import SkinInferenceConfig
    from unittest.mock import MagicMock

    cfg = SkinInferenceConfig()
    engine = SkinDiagnosticEngine(cfg, MagicMock(), MagicMock(), MagicMock())

    # class 5 is 'normal'
    probs = np.array([0.01, 0.01, 0.02, 0.01, 0.02, 0.90, 0.02, 0.01], dtype=np.float32)

    triage, alert, note = engine.determine_triage(probs, top_pred_idx=5)
    assert triage == "HEALTHY_SKIN"
    assert alert is False
    assert "healthy skin" in note.lower()


def test_non_melanoma_malignancy_triage() -> None:
    """Assert basal cell carcinoma (bcc) triggers SPECIALIST_REVIEW."""
    from app.engine.diagnostic_engine import SkinDiagnosticEngine
    from app.core.config import SkinInferenceConfig
    from unittest.mock import MagicMock

    cfg = SkinInferenceConfig()
    engine = SkinDiagnosticEngine(cfg, MagicMock(), MagicMock(), MagicMock())

    # class 1 is 'bcc'
    probs = np.array([0.05, 0.75, 0.05, 0.02, 0.05, 0.02, 0.04, 0.02], dtype=np.float32)

    triage, alert, note = engine.determine_triage(probs, top_pred_idx=1)
    assert triage == "SPECIALIST_REVIEW"
    assert alert is False


def test_otsu_roi_extraction_bounding_box() -> None:
    """Assert Otsu adaptive ROI cropping extracts lesion region and handles margins."""
    from app.engine.preprocessor import SkinPreprocessor
    from app.core.config import SkinInferenceConfig

    cfg = SkinInferenceConfig(enable_otsu_roi=True)
    preprocessor = SkinPreprocessor(cfg)

    # Create synthetic image: 400x400 skin-tone image with a centered dark lesion (80x80)
    arr = np.full((400, 400, 3), [210, 180, 140], dtype=np.uint8)
    arr[160:240, 160:240] = [60, 40, 30]  # dark lesion occupies 6400 / 160000 = 4% area
    img = Image.fromarray(arr)

    cropped = preprocessor.extract_lesion_roi(img)
    cw, ch = cropped.size

    # Cropped size must be tighter than original 400x400
    assert cw < 400
    assert ch < 400
    assert cw > 50
    assert ch > 50

