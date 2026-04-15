"""
Signal preprocessing module for ECG inference.
Normalizes raw ECG records and converts them into model-ready chunked tensors.
"""

from __future__ import annotations

import numpy as np
import torch
import wfdb
from torch import Tensor

from src.ecg.config import ECGInferenceConfig


class ECGPreprocessor:
    """Loads and normalizes a raw PTB-XL ECG signal for inference."""

    def __init__(self, cfg: ECGInferenceConfig) -> None:
        self.cfg = cfg

    def process(self, file_path: str) -> tuple[Tensor, np.ndarray]:
        """Convert a raw ECG record into the model-ready tensor shape."""

        signal, _ = wfdb.rdsamp(file_path)
        normalized = (signal - np.mean(signal, axis=0)) / (np.std(signal, axis=0) + 1e-6)

        first_chunk = torch.tensor(normalized[: self.cfg.seq_length, :].T, dtype=torch.float32)
        second_chunk = torch.tensor(
            normalized[self.cfg.seq_length : self.cfg.full_signal_length, :].T,
            dtype=torch.float32,
        )
        stacked = torch.stack([first_chunk, second_chunk]).unsqueeze(0)
        return stacked, normalized
