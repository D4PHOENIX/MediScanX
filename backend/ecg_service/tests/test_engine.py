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
            
        # 2. Clipped signal length (e.g., 300 instead of 500)
        mock_rdsamp.return_value = (np.random.randn(300, 12), None)
        with pytest.raises(SignalLengthMismatchError):
            preprocessor.process_wfdb("fake_record")
