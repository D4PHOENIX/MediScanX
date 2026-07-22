"""Tests for the CXR Inference Service Diagnostic Engine."""

from unittest.mock import MagicMock
import pytest
import numpy as np

# ---------------------------------------------------------------------------
#  Test 10 — Domain Exceptions in Preprocessor (Image Read Error)
# ---------------------------------------------------------------------------
def test_preprocessor_image_read_error() -> None:
    from app.engine.preprocessor import CXRInferencePreprocessor
    from app.core.config import Settings as CXRInferenceConfig
    from app.core.exceptions import ImageReadError
    cfg = CXRInferenceConfig()
    preprocessor = CXRInferencePreprocessor(cfg)
    with pytest.raises(ImageReadError):
        preprocessor.process("non_existent_image_path_to_trigger_error.jpg")


# ---------------------------------------------------------------------------
#  Test 11 — Domain Exceptions in Diagnostic Engine (Invalid Tensor Shape)
# ---------------------------------------------------------------------------
def test_diagnostic_engine_invalid_shape() -> None:
    from app.engine.diagnostic_engine import CXRDiagnosticEngine
    from app.core.config import Settings as CXRInferenceConfig
    from app.core.exceptions import InvalidTensorShapeError
    import torch
    cfg = CXRInferenceConfig()
    mock_preprocessor = MagicMock()
    # return bad shape to trigger exception
    mock_preprocessor.process.return_value = (torch.zeros((1, 3, 100, 100)), np.zeros((100, 100, 3), dtype=np.uint8))
    engine = CXRDiagnosticEngine(cfg, MagicMock(), mock_preprocessor, MagicMock())
    with pytest.raises(InvalidTensorShapeError):
        engine.run_diagnostic("dummy.jpg")


# ---------------------------------------------------------------------------
#  Test 12 — Domain Exceptions in Diagnostic Engine (OOM / Model Inference)
# ---------------------------------------------------------------------------
def test_diagnostic_engine_oom() -> None:
    from app.engine.diagnostic_engine import CXRDiagnosticEngine
    from app.core.config import Settings as CXRInferenceConfig
    from app.core.exceptions import ModelInferenceError
    import torch
    cfg = CXRInferenceConfig()
    mock_preprocessor = MagicMock()
    mock_preprocessor.process.return_value = (torch.zeros((1, 3, 320, 320)), np.zeros((320, 320, 3), dtype=np.uint8))
    mock_model = MagicMock()
    mock_model.side_effect = RuntimeError("CUDA out of memory")
    engine = CXRDiagnosticEngine(cfg, mock_model, mock_preprocessor, MagicMock())
    with pytest.raises(ModelInferenceError):
        engine.run_diagnostic("dummy.jpg")
