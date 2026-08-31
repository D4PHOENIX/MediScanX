"""Tests for the ECG Inference Service using pure mocking for ultra-fast execution."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
#  Test 1 — Configuration loading
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_configuration_loading() -> None:
    """Verify that Settings reads the correct env vars
    and expose the expected architecture constants.
    """
    import os
    with patch.dict(os.environ, {
        "ECG_ONNX_PATH": "/models/fake.onnx",
        "ECG_CKPT_PATH": "/models/fake.ckpt",
    }):
        from app.core.config import Settings

        settings = Settings()
        cfg = Settings(
            onnx_model_path=settings.ecg_onnx_path,
            pytorch_ckpt_path=settings.ecg_ckpt_path,
        )

        assert cfg.onnx_model_path == "/models/fake.onnx"
        assert cfg.pytorch_ckpt_path == "/models/fake.ckpt"
        assert hasattr(cfg, "seq_length")
        assert hasattr(cfg, "ecg_labels")
        assert cfg.num_leads == 12
        assert cfg.num_classes == 5
        assert cfg.ecg_labels == ["NORM", "MI", "STTC", "CD", "HYP"]
