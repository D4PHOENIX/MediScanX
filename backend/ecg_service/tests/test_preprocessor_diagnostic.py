import os
import pytest
from unittest.mock import patch
import numpy as np
import cv2
import torch
from app.engine.preprocessor import ECGPreprocessor
from app.core.config import Settings
from app.core.exceptions import ECGExtractionError

def test_diagnostic_mode_defaults_to_false_when_no_env_var():
    cfg = Settings()
    assert cfg.ecg_diagnostic_mode is False
    assert cfg.ecg_diagnostic_dir == "/app/data/ecg_diagnostics"

@patch("app.engine.preprocessor._ECGGridSlicer.slice_image")
@patch("app.engine.preprocessor._PinkGridRemover.remove_grid")
@patch("app.engine.preprocessor._WaveformDigitizer.extract_1d_signal")
def test_diagnostic_makedirs_permission_error_does_not_fail_inference(mock_extract, mock_remove, mock_slice):
    mock_remove.return_value = np.zeros((100, 100), dtype=np.uint8)
    mock_slice.return_value = {
        'I': np.zeros((10, 10), dtype=np.uint8), 'II': np.zeros((10, 10), dtype=np.uint8), 'III': np.zeros((10, 10), dtype=np.uint8),
        'aVR': np.zeros((10, 10), dtype=np.uint8), 'aVL': np.zeros((10, 10), dtype=np.uint8), 'aVF': np.zeros((10, 10), dtype=np.uint8),
        'V1': np.zeros((10, 10), dtype=np.uint8), 'V2': np.zeros((10, 10), dtype=np.uint8), 'V3': np.zeros((10, 10), dtype=np.uint8),
        'V4': np.zeros((10, 10), dtype=np.uint8), 'V5': np.zeros((10, 10), dtype=np.uint8), 'V6': np.zeros((10, 10), dtype=np.uint8),
    }
    mock_extract.return_value = (np.zeros(500, dtype=np.float32), 1.0, False)
    
    cfg = Settings()
    preprocessor = ECGPreprocessor(cfg)
    
    with patch("os.makedirs", side_effect=PermissionError("Permission denied")):
        tensor, signals = preprocessor.process_image("dummy.jpg", diagnostic_mode=True)
        assert tensor is not None
        assert signals is not None
        assert tensor.shape == (1, 12, 500)

@patch("app.engine.preprocessor._ECGGridSlicer.slice_image")
@patch("app.engine.preprocessor._PinkGridRemover.remove_grid")
@patch("app.engine.preprocessor._WaveformDigitizer.extract_1d_signal")
def test_diagnostic_imwrite_oserror_returns_bit_identical(mock_extract, mock_remove, mock_slice):
    mock_remove.return_value = np.zeros((100, 100), dtype=np.uint8)
    mock_slice.return_value = {
        'I': np.zeros((10, 10), dtype=np.uint8), 'II': np.zeros((10, 10), dtype=np.uint8), 'III': np.zeros((10, 10), dtype=np.uint8),
        'aVR': np.zeros((10, 10), dtype=np.uint8), 'aVL': np.zeros((10, 10), dtype=np.uint8), 'aVF': np.zeros((10, 10), dtype=np.uint8),
        'V1': np.zeros((10, 10), dtype=np.uint8), 'V2': np.zeros((10, 10), dtype=np.uint8), 'V3': np.zeros((10, 10), dtype=np.uint8),
        'V4': np.zeros((10, 10), dtype=np.uint8), 'V5': np.zeros((10, 10), dtype=np.uint8), 'V6': np.zeros((10, 10), dtype=np.uint8),
    }
    mock_extract.return_value = (np.random.randn(500).astype(np.float32), 1.0, False)
    
    cfg = Settings()
    preprocessor = ECGPreprocessor(cfg)
    
    with patch("os.makedirs") as mock_makedirs, patch("cv2.imwrite") as mock_imwrite, patch("numpy.save") as mock_save:
        tensor_off, signals_off = preprocessor.process_image("dummy.jpg", diagnostic_mode=False)
        mock_makedirs.assert_not_called()
        mock_imwrite.assert_not_called()
        mock_save.assert_not_called()

    with patch("os.makedirs"), patch("cv2.imwrite", side_effect=OSError("Write failed")), patch("numpy.save"):
        tensor_on, signals_on = preprocessor.process_image("dummy.jpg", diagnostic_mode=True)
    
    assert torch.equal(tensor_off, tensor_on)
    np.testing.assert_array_equal(signals_off, signals_on)

@patch("app.engine.preprocessor._ECGGridSlicer.slice_image")
@patch("app.engine.preprocessor._PinkGridRemover.remove_grid")
@patch("app.engine.preprocessor._WaveformDigitizer.extract_1d_signal")
def test_genuine_signal_error_still_raises(mock_extract, mock_remove, mock_slice):
    mock_remove.return_value = np.zeros((100, 100), dtype=np.uint8)
    mock_slice.return_value = {
        'I': np.zeros((10, 10), dtype=np.uint8), 'II': np.zeros((10, 10), dtype=np.uint8), 'III': np.zeros((10, 10), dtype=np.uint8),
        'aVR': np.zeros((10, 10), dtype=np.uint8), 'aVL': np.zeros((10, 10), dtype=np.uint8), 'aVF': np.zeros((10, 10), dtype=np.uint8),
        'V1': np.zeros((10, 10), dtype=np.uint8), 'V2': np.zeros((10, 10), dtype=np.uint8), 'V3': np.zeros((10, 10), dtype=np.uint8),
        'V4': np.zeros((10, 10), dtype=np.uint8), 'V5': np.zeros((10, 10), dtype=np.uint8), 'V6': np.zeros((10, 10), dtype=np.uint8),
    }
    mock_extract.return_value = (None, 0.5, True) # Simulate failure
    
    cfg = Settings()
    preprocessor = ECGPreprocessor(cfg)
    
    with patch("os.makedirs", side_effect=PermissionError("Permission denied")):
        with pytest.raises(ECGExtractionError):
            preprocessor.process_image("dummy.jpg", diagnostic_mode=True)
