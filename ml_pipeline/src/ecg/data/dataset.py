"""
Custom PyTorch dataset implementation for PTB-XL ECG records.
Loads raw signals, normalizes them, and splits each record into two chunks.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd
import torch
import wfdb
from torch import Tensor
from torch.utils.data import Dataset

from src.ecg.config import ECGTrainingConfig


class PTBXLDataset(Dataset[tuple[Tensor, Tensor]]):
    """Dataset for PTB-XL ECG records using a two-chunk representation."""

    def __init__(self, dataframe: pd.DataFrame, root_dir: str, cfg: ECGTrainingConfig) -> None:
        self.dataframe = dataframe
        self.root_dir = root_dir
        self.cfg = cfg
        self.indices = self.dataframe.index.tolist()

    def __len__(self) -> int:
        """Return the dataset size."""

        return len(self.indices)

    def __getitem__(self, idx: int) -> tuple[Tensor, Tensor]:
        """Load, normalize, and chunk a single ECG record."""

        ecg_id = self.indices[idx]
        filename = str(self.dataframe.loc[ecg_id, "filename"])
        labels = self.dataframe.loc[ecg_id, self.cfg.target_classes].values.astype(np.float32)
        file_path = os.path.join(self.root_dir, filename)

        try:
            signal, _ = wfdb.rdsamp(file_path)
        except Exception as exc:
            print(f"Error loading {file_path}: {exc}")
            empty_signal = torch.zeros(2, self.cfg.num_leads, self.cfg.seq_length)
            empty_labels = torch.zeros(len(self.cfg.target_classes))
            return empty_signal, empty_labels

        normalized = (signal - np.mean(signal, axis=0)) / (np.std(signal, axis=0) + 1e-6)
        first_chunk = torch.tensor(normalized[: self.cfg.seq_length, :].T, dtype=torch.float32)
        second_chunk = torch.tensor(
            normalized[self.cfg.seq_length : self.cfg.full_signal_length, :].T,
            dtype=torch.float32,
        )
        label_tensor = torch.tensor(labels, dtype=torch.float32)
        return torch.stack([first_chunk, second_chunk]), label_tensor
