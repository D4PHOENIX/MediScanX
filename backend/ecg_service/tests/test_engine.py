"""Tests for the ECG Inference Service using pure mocking for ultra-fast execution."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
#  Test 8 — Preprocessor Fault Injection (Missing Leads / Corrupt Dimensions)
# ---------------------------------------------------------------------------
def test_preprocessor_fault_injection() -> None:
    from app.engine.preprocessor import ECGPreprocessor
    from app.core.config import Settings
    from app.core.exceptions import InvalidLeadCountError, SignalLengthMismatchError
    import numpy as np
    
    cfg = Settings()
    preprocessor = ECGPreprocessor(cfg)
    
    # Mock wfdb.rdsamp to return a corrupt signal
    with patch("wfdb.rdsamp") as mock_rdsamp, patch("pathlib.Path.exists", return_value=True):
        # 1. Missing leads (e.g., 10 instead of 12)
        mock_rdsamp.return_value = (np.random.randn(500, 10), None)
        with pytest.raises(InvalidLeadCountError):
            preprocessor.process_wfdb("fake_record")
            
        # 2. Genuinely short signal (150 samples < 250 contract) triggers mismatch
        mock_rdsamp.return_value = (np.random.randn(150, 12), None)
        with pytest.raises(SignalLengthMismatchError):
            preprocessor.process_wfdb("fake_record")


def test_finiteness_gate() -> None:
    from app.engine.diagnostic_engine import ECGDiagnosticEngine
    from app.core.exceptions import ECGInferenceError
    import numpy as np
    import torch
    
    mock_cfg = MagicMock()
    mock_cfg.device = torch.device('cpu')
    mock_preprocessor = MagicMock()
    
    # Preprocessor returns a tensor with a NaN
    bad_tensor = torch.ones((1, 12, 250))
    bad_tensor[0, 0, 0] = float('nan')
    mock_preprocessor.process_wfdb.return_value = (bad_tensor, np.ones((12, 250)))
    
    engine = ECGDiagnosticEngine(
        cfg=mock_cfg,
        onnx_session=MagicMock(),
        model=None,
        preprocessor=mock_preprocessor,
        xai_engine=None
    )
    
    with pytest.raises(ECGInferenceError, match="non-finite values"):
        engine.run_diagnostic("fake", input_type="wfdb")
