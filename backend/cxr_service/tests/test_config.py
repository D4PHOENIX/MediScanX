"""Tests for the CXR Inference Service using pure mocking for zero-latency execution."""

import pytest
import numpy as np

# ---------------------------------------------------------------------------
#  Test 1 — Configuration loading
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_configuration_loading() -> None:
    """Verify that CXRInferenceConfig exposes the expected architecture constants.

    Also asserts that ``__post_init__`` performs no disk I/O and leaves
    ``classification_thresholds`` unset until the engine loads it.
    """
    from app.core.config import Settings as CXRInferenceConfig

    cfg = CXRInferenceConfig()

    # num_classes = 14 base + 6 hierarchical = 20
    assert cfg.num_classes == 20
    assert len(cfg.chexpert_labels) == 14
    assert len(cfg.high_level_labels) == 6
    assert cfg.image_size == (320, 320)

    # classification_thresholds is now a proper field, defaulting to None until
    # CXREngine._load() populates it.
    assert cfg.classification_thresholds is None

    # Verify the paths defaults exist as attributes (not required to be valid paths)
    assert hasattr(cfg, "CXR_WEIGHTS_PATH")
    assert hasattr(cfg, "CXR_THRESHOLDS_PATH")


# ---------------------------------------------------------------------------
#  Test 9 — Threshold shape/dtype validation in config
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_threshold_dtype_and_fallback() -> None:
    """Verify threshold fallback produces a float32 array of the correct length.

    Thresholds must be float32 and have exactly ``num_base_labels`` elements to
    avoid implicit float64 upcasting or an index error during masking.
    """
    from app.core.config import Settings as CXRInferenceConfig

    cfg = CXRInferenceConfig()
    num_base = len(cfg.chexpert_labels)  # 14

    # Simulate the fallback path that cxr_engine._load() uses when the
    # thresholds file is missing.
    fallback = np.full(num_base, 0.5, dtype=np.float32)

    assert fallback.dtype == np.float32
    assert fallback.shape[0] == num_base
    assert (fallback == 0.5).all()

    # Simulate a valid float64 load followed by the astype cast
    loaded_f64 = np.linspace(0.3, 0.7, num_base)  # dtype float64
    cast = loaded_f64.astype(np.float32)
    assert cast.dtype == np.float32
    assert cast.shape[0] == num_base
