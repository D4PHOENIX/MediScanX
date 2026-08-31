import numpy as np
from app.engine.digitizer import digitize_ecg

def test_digitize_ecg_fails_closed_on_blank_image():
    img = np.zeros((800, 1200, 3), dtype=np.uint8)
    result = digitize_ecg(img)
    assert result["ok"] is False
    assert result["failure_reason"] == "Preprocessing failed: insufficient_detectable_ink"
    assert all(v is None for v in result["signals"].values())
    assert result["sampling_rate_hz"] is None
