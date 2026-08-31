"""Tests for the Skin Lesion Inference Service configuration."""

import os
import pytest

@pytest.mark.asyncio
async def test_configuration_loading() -> None:
    """Verify that SkinInferenceConfig exposes the expected architecture constants."""
    from app.core.config import SkinInferenceConfig

    cfg = SkinInferenceConfig()

    assert hasattr(cfg, "skin_labels")
    assert hasattr(cfg, "skin_abbreviations")
    assert hasattr(cfg, "mean")
    assert hasattr(cfg, "std")
    assert hasattr(cfg, "heatmap_alpha")
    assert hasattr(cfg, "heatmap_beta")
    assert len(cfg.skin_labels) == 7
    assert len(cfg.skin_abbreviations) == 7
    # Verify standard ImageNet normalisation constants
    assert cfg.mean == [0.485, 0.456, 0.406]
    assert cfg.std  == [0.229, 0.224, 0.225]
    # Verify MobileNet input dimensions
    assert cfg.image_size == (224, 224)
