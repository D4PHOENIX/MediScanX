"""
Data orchestration and routing module for ECG training.
Creates train and validation splits and wraps them in dataloaders.
"""

from __future__ import annotations

from sklearn.model_selection import train_test_split
from torch import Tensor
from torch.utils.data import DataLoader

from src.ecg.config import ECGTrainingConfig
from src.ecg.data.dataset import PTBXLDataset
from src.ecg.data.metadata import PTBXLMetadataProcessor


class ECGDataModule:
    """Factory class for metadata routing, dataset creation, and dataloaders."""

    def __init__(self, cfg: ECGTrainingConfig) -> None:
        self.cfg = cfg
        self.class_names: list[str] = []

    def setup(self) -> tuple[DataLoader[tuple[Tensor, Tensor]], DataLoader[tuple[Tensor, Tensor]]]:
        """Create train and validation dataloaders."""

        labels_df, self.class_names = PTBXLMetadataProcessor.load_and_process(self.cfg)
        train_df, val_df = train_test_split(
            labels_df,
            test_size=self.cfg.val_size,
            random_state=self.cfg.random_state,
        )

        train_dataset = PTBXLDataset(train_df, self.cfg.data_dir, self.cfg)
        val_dataset = PTBXLDataset(val_df, self.cfg.data_dir, self.cfg)

        train_loader = DataLoader(
            train_dataset,
            batch_size=self.cfg.batch_size,
            shuffle=True,
            num_workers=self.cfg.num_workers,
            pin_memory=self.cfg.device.type == "cuda",
        )
        val_loader = DataLoader(
            val_dataset,
            batch_size=self.cfg.batch_size,
            shuffle=False,
            num_workers=self.cfg.num_workers,
            pin_memory=self.cfg.device.type == "cuda",
        )

        print(f"Data routing complete. Train: {len(train_dataset)} | Val: {len(val_dataset)}")
        return train_loader, val_loader
