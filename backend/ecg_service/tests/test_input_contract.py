"""B19 — Input Contract Tests: WFDB and Image paths must produce identical duration tensors.

Surfaces task B19 (86eydn6yn) / B19.1 (86eydnwwm) / B19.2 (86eydnwxc).

Trained contract (3rd Experimentation, Notebook 04b):
    - Dataset      : PTB-XL, 100 Hz version
    - Sample rate  : 100 Hz
    - Duration     : 2.5 seconds
    - Seq length   : 250 samples  (= 2.5 s × 100 Hz)
    - Leads        : 12
    - Classes      : 5  (NORM, MI, STTC, CD, HYP)

Both input paths must produce tensors of shape (1, 12, 250) — float32, finite,
with no NaN or Inf values — before being passed to the model.

Known limitation (out of scope for B19):
    The 4-band rhythm strip (Lead II, full 10 s) is not processed.
    It is architecturally incompatible with the 2.5 s trained window and is not
    required for any of the 5 output classes (all morphology-based).
    Rhythm analysis would require a separate model trained on longer windows.
"""

import numpy as np
import pytest
import torch
from unittest.mock import patch

from app.core.config import Settings
from app.engine.preprocessor import ECGPreprocessor


# ---------------------------------------------------------------------------
# Shared constants — single source of truth for the trained contract
# ---------------------------------------------------------------------------

SAMPLE_RATE_HZ: int = 100          # PTB-XL 100 Hz version
WINDOW_DURATION_S: float = 2.5     # 2.5-second segments (Notebook 02b / 04b)
CONTRACT_SEQ_LEN: int = 250        # = SAMPLE_RATE_HZ * WINDOW_DURATION_S
CONTRACT_LEADS: int = 12
CONTRACT_CLASSES: int = 5
CONTRACT_LABELS: list = ["NORM", "MI", "STTC", "CD", "HYP"]
CONTRACT_THRESHOLDS: list = [0.49, 0.38, 0.47, 0.49, 0.46]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_lead_mock_slices(signal_len: int = CONTRACT_SEQ_LEN) -> dict:
    """Return a mock lead-image dict for all 12 standard leads."""
    leads = ["I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6"]
    return {lead: np.zeros((10, signal_len), dtype=np.uint8) for lead in leads}


# ===========================================================================
# B19.1 — Trained contract is known and encoded in Settings
# ===========================================================================

class TestB19_1_TrainedContract:
    """Assert that Settings encodes the correct trained contract.

    This is the canonical answer to B19.1: 250 samples, 100 Hz, 2.5 s, 12 leads.
    """

    def test_seq_length_matches_trained_contract(self):
        """cfg.seq_length must equal 250 — 2.5 s at 100 Hz (PTB-XL 100 Hz version)."""
        cfg = Settings()
        assert cfg.seq_length == CONTRACT_SEQ_LEN, (
            f"cfg.seq_length={cfg.seq_length} does not match the trained contract "
            f"({CONTRACT_SEQ_LEN} samples = {WINDOW_DURATION_S}s @ {SAMPLE_RATE_HZ}Hz)."
        )

    def test_seq_length_encodes_correct_duration(self):
        """250 samples at 100 Hz must equal exactly 2.5 seconds."""
        cfg = Settings()
        computed_duration = cfg.seq_length / SAMPLE_RATE_HZ
        assert computed_duration == WINDOW_DURATION_S, (
            f"seq_length={cfg.seq_length} / {SAMPLE_RATE_HZ}Hz = "
            f"{computed_duration}s, expected {WINDOW_DURATION_S}s."
        )

    def test_num_leads_is_12(self):
        """Model was trained on 12-lead ECG recordings."""
        cfg = Settings()
        assert cfg.num_leads == CONTRACT_LEADS

    def test_num_classes_is_5(self):
        """Model outputs 5 classes: NORM, MI, STTC, CD, HYP."""
        cfg = Settings()
        assert cfg.num_classes == CONTRACT_CLASSES

    def test_ecg_labels_match_trained_order(self):
        """Label order must match the training class indices exactly."""
        cfg = Settings()
        assert cfg.ecg_labels == CONTRACT_LABELS, (
            f"ecg_labels={cfg.ecg_labels} does not match trained order {CONTRACT_LABELS}."
        )

    def test_per_class_thresholds_present_and_valid(self):
        """Per-class calibrated thresholds must exist, one per class, all in (0, 1)."""
        cfg = Settings()
        assert len(cfg.ecg_thresholds) == cfg.num_classes, (
            f"Expected {cfg.num_classes} thresholds, got {len(cfg.ecg_thresholds)}."
        )
        for label, threshold in zip(cfg.ecg_labels, cfg.ecg_thresholds):
            assert 0.0 < threshold < 1.0, (
                f"Threshold for {label}={threshold} is outside valid range (0, 1)."
            )

    def test_per_class_thresholds_match_calibrated_values(self):
        """Thresholds must equal the Fold-9 calibrated values from Notebook 04b."""
        cfg = Settings()
        assert cfg.ecg_thresholds == CONTRACT_THRESHOLDS, (
            f"ecg_thresholds={cfg.ecg_thresholds} "
            f"do not match calibrated values {CONTRACT_THRESHOLDS}."
        )


# ===========================================================================
# B19.2 — WFDB path output shape and duration
# ===========================================================================

class TestB19_2_WFDBPath:
    """Assert that process_wfdb produces a tensor representing 2.5 s at 100 Hz.

    Reconciliation: PTB-XL records are 10 s (1000 samples at 100 Hz).
    The preprocessor correctly windows to the first 250-sample segment.
    Truncating the remaining 750 samples is deliberate — the model was trained
    on 250-sample segments, NOT on full 10-second records.
    """

    def _run_wfdb(self, n_samples: int) -> tuple:
        """Run process_wfdb with a mocked WFDB record of n_samples length."""
        cfg = Settings()
        preprocessor = ECGPreprocessor(cfg)
        mock_signal = np.random.randn(n_samples, 12).astype(np.float64)
        with patch("wfdb.rdsamp", return_value=(mock_signal, None)), \
             patch("pathlib.Path.exists", return_value=True):
            return preprocessor.process_wfdb("mock_record")

    def test_wfdb_output_tensor_shape(self):
        """WFDB path must produce tensor of shape (1, 12, 250)."""
        tensor, _ = self._run_wfdb(n_samples=1000)   # full 10 s PTB-XL record
        assert tensor.shape == (1, CONTRACT_LEADS, CONTRACT_SEQ_LEN), (
            f"WFDB path produced {tuple(tensor.shape)}, "
            f"expected (1, {CONTRACT_LEADS}, {CONTRACT_SEQ_LEN})."
        )

    def test_wfdb_output_dtype_is_float32(self):
        """Preprocessed tensor must be float32 for the model."""
        tensor, _ = self._run_wfdb(n_samples=1000)
        assert tensor.dtype == torch.float32, (
            f"WFDB tensor dtype={tensor.dtype}, expected torch.float32."
        )

    def test_wfdb_output_is_finite(self):
        """Preprocessed tensor must contain no NaN or Inf values."""
        tensor, _ = self._run_wfdb(n_samples=1000)
        assert torch.isfinite(tensor).all(), (
            "WFDB tensor contains NaN or Inf after preprocessing."
        )

    def test_wfdb_signal_array_shape(self):
        """Companion signal array must be (12, 250) for downstream XAI."""
        _, signal_array = self._run_wfdb(n_samples=1000)
        assert signal_array.shape == (CONTRACT_LEADS, CONTRACT_SEQ_LEN), (
            f"WFDB signal_array shape={signal_array.shape}, "
            f"expected ({CONTRACT_LEADS}, {CONTRACT_SEQ_LEN})."
        )

    def test_wfdb_longer_record_is_correctly_windowed(self):
        """A 10-second (1000-sample) record must be windowed to 250, not rejected."""
        tensor, _ = self._run_wfdb(n_samples=1000)
        assert tensor.shape[2] == CONTRACT_SEQ_LEN

    def test_wfdb_encodes_correct_duration(self):
        """Output length must encode exactly 2.5 seconds at 100 Hz."""
        tensor, _ = self._run_wfdb(n_samples=1000)
        duration = tensor.shape[2] / SAMPLE_RATE_HZ
        assert duration == WINDOW_DURATION_S, (
            f"WFDB tensor encodes {duration}s, expected {WINDOW_DURATION_S}s."
        )


# ===========================================================================
# B19.2 — Image path output shape and duration
# ===========================================================================

class TestB19_2_ImagePath:
    """Assert that process_image produces a tensor representing 2.5 s at 100 Hz.

    Reconciliation: each of the 12 lead boxes in the 3x4 grid spans 2.5 seconds.
    The optical digitizer resamples each column strip to cfg.seq_length = 250.
    This is a 100% natural fit — no time warping occurs.

    Known limitation (out of scope for B19):
        The 4th-row rhythm strip (Lead II, 10 s) is not processed because it is
        architecturally incompatible with the 2.5 s trained model.
    """

    def _make_image_mocks(self, signal_len: int = CONTRACT_SEQ_LEN):
        """Return (remove_patch, slice_patch, extract_patch) with correct shapes."""
        mock_binary = np.zeros((300, 1200), dtype=np.uint8)
        mock_slices = _all_lead_mock_slices(signal_len)
        mock_signal = np.random.randn(signal_len).astype(np.float32)
        return mock_binary, mock_slices, (mock_signal, 1.0, False)

    def test_image_output_tensor_shape(self):
        """Image path must produce tensor of shape (1, 12, 250)."""
        mock_binary, mock_slices, mock_extract = self._make_image_mocks()
        cfg = Settings()
        preprocessor = ECGPreprocessor(cfg)

        with patch("app.engine.preprocessor._PinkGridRemover.remove_grid",
                   return_value=mock_binary), \
             patch("app.engine.preprocessor._ECGGridSlicer.slice_image",
                   return_value=mock_slices), \
             patch("app.engine.preprocessor._WaveformDigitizer.extract_1d_signal",
                   return_value=mock_extract):
            tensor, _ = preprocessor.process_image("dummy.jpg")

        assert tensor.shape == (1, CONTRACT_LEADS, CONTRACT_SEQ_LEN), (
            f"Image path produced {tuple(tensor.shape)}, "
            f"expected (1, {CONTRACT_LEADS}, {CONTRACT_SEQ_LEN})."
        )

    def test_image_output_dtype_is_float32(self):
        """Preprocessed tensor must be float32 for the model."""
        mock_binary, mock_slices, mock_extract = self._make_image_mocks()
        cfg = Settings()
        preprocessor = ECGPreprocessor(cfg)

        with patch("app.engine.preprocessor._PinkGridRemover.remove_grid",
                   return_value=mock_binary), \
             patch("app.engine.preprocessor._ECGGridSlicer.slice_image",
                   return_value=mock_slices), \
             patch("app.engine.preprocessor._WaveformDigitizer.extract_1d_signal",
                   return_value=mock_extract):
            tensor, _ = preprocessor.process_image("dummy.jpg")

        assert tensor.dtype == torch.float32, (
            f"Image tensor dtype={tensor.dtype}, expected torch.float32."
        )

    def test_image_output_is_finite(self):
        """Preprocessed tensor must contain no NaN or Inf values."""
        mock_binary, mock_slices, mock_extract = self._make_image_mocks()
        cfg = Settings()
        preprocessor = ECGPreprocessor(cfg)

        with patch("app.engine.preprocessor._PinkGridRemover.remove_grid",
                   return_value=mock_binary), \
             patch("app.engine.preprocessor._ECGGridSlicer.slice_image",
                   return_value=mock_slices), \
             patch("app.engine.preprocessor._WaveformDigitizer.extract_1d_signal",
                   return_value=mock_extract):
            tensor, _ = preprocessor.process_image("dummy.jpg")

        assert torch.isfinite(tensor).all(), (
            "Image tensor contains NaN or Inf after preprocessing."
        )

    def test_image_encodes_correct_duration(self):
        """Output length must encode exactly 2.5 seconds at 100 Hz."""
        mock_binary, mock_slices, mock_extract = self._make_image_mocks()
        cfg = Settings()
        preprocessor = ECGPreprocessor(cfg)

        with patch("app.engine.preprocessor._PinkGridRemover.remove_grid",
                   return_value=mock_binary), \
             patch("app.engine.preprocessor._ECGGridSlicer.slice_image",
                   return_value=mock_slices), \
             patch("app.engine.preprocessor._WaveformDigitizer.extract_1d_signal",
                   return_value=mock_extract):
            tensor, _ = preprocessor.process_image("dummy.jpg")

        duration = tensor.shape[2] / SAMPLE_RATE_HZ
        assert duration == WINDOW_DURATION_S, (
            f"Image tensor encodes {duration}s, expected {WINDOW_DURATION_S}s."
        )


# ===========================================================================
# B19.2 — Both paths represent the SAME duration and sample rate
# ===========================================================================

class TestB19_2_BothPathsConsistent:
    """Assert WFDB and image paths produce tensors representing the same contract.

    This is the core requirement of B19.2: both paths must agree on shape,
    dtype, and duration so that the ground-truth harness (B13) can compare
    them against a valid common baseline.
    """

    def _wfdb_tensor(self) -> torch.Tensor:
        cfg = Settings()
        preprocessor = ECGPreprocessor(cfg)
        mock_signal = np.random.randn(1000, 12).astype(np.float64)
        with patch("wfdb.rdsamp", return_value=(mock_signal, None)), \
             patch("pathlib.Path.exists", return_value=True):
            tensor, _ = preprocessor.process_wfdb("mock_record")
        return tensor

    def _image_tensor(self) -> torch.Tensor:
        mock_binary = np.zeros((300, 1200), dtype=np.uint8)
        mock_slices = _all_lead_mock_slices()
        mock_signal = np.random.randn(CONTRACT_SEQ_LEN).astype(np.float32)
        cfg = Settings()
        preprocessor = ECGPreprocessor(cfg)
        with patch("app.engine.preprocessor._PinkGridRemover.remove_grid",
                   return_value=mock_binary), \
             patch("app.engine.preprocessor._ECGGridSlicer.slice_image",
                   return_value=mock_slices), \
             patch("app.engine.preprocessor._WaveformDigitizer.extract_1d_signal",
                   return_value=(mock_signal, 1.0, False)):
            tensor, _ = preprocessor.process_image("dummy.jpg")
        return tensor

    def test_both_paths_produce_same_shape(self):
        """WFDB and image paths must produce tensors of identical shape."""
        wfdb_t = self._wfdb_tensor()
        img_t = self._image_tensor()
        assert wfdb_t.shape == img_t.shape, (
            f"Shape mismatch: WFDB={tuple(wfdb_t.shape)}, image={tuple(img_t.shape)}. "
            "The ground-truth harness (B13) cannot compare paths with different shapes."
        )

    def test_both_paths_produce_same_dtype(self):
        """WFDB and image paths must both produce float32 tensors."""
        wfdb_t = self._wfdb_tensor()
        img_t = self._image_tensor()
        assert wfdb_t.dtype == img_t.dtype == torch.float32, (
            f"Dtype mismatch: WFDB={wfdb_t.dtype}, image={img_t.dtype}."
        )

    def test_both_paths_represent_same_duration(self):
        """Both paths must encode 2.5 seconds of signal at 100 Hz."""
        wfdb_t = self._wfdb_tensor()
        img_t = self._image_tensor()
        wfdb_duration = wfdb_t.shape[2] / SAMPLE_RATE_HZ
        img_duration = img_t.shape[2] / SAMPLE_RATE_HZ
        assert wfdb_duration == img_duration == WINDOW_DURATION_S, (
            f"Duration mismatch: WFDB={wfdb_duration}s, image={img_duration}s, "
            f"expected both to be {WINDOW_DURATION_S}s."
        )

    def test_both_paths_have_12_leads(self):
        """Both paths must carry all 12 leads for the 12-lead ECG model."""
        wfdb_t = self._wfdb_tensor()
        img_t = self._image_tensor()
        assert wfdb_t.shape[1] == img_t.shape[1] == CONTRACT_LEADS

    def test_both_paths_match_config_contract(self):
        """Both tensor shapes must exactly match (1, cfg.num_leads, cfg.seq_length)."""
        cfg = Settings()
        expected = (1, cfg.num_leads, cfg.seq_length)
        wfdb_t = self._wfdb_tensor()
        img_t = self._image_tensor()
        assert tuple(wfdb_t.shape) == expected, (
            f"WFDB shape {tuple(wfdb_t.shape)} != config contract {expected}."
        )
        assert tuple(img_t.shape) == expected, (
            f"Image shape {tuple(img_t.shape)} != config contract {expected}."
        )
