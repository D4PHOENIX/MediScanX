"""
Centralized configuration module for the ECG pipeline.
Defines typed dataclasses for training and inference settings.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import torch


@dataclass
class ECGTrainingConfig:
    """Centralized configuration for the ECG training pipeline."""

    seed: int = 42
    batch_size: int = 64
    max_epochs: int = 30
    learning_rate: float = 1e-3
    sample_rate: int = 100
    seq_length: int = 500
    full_signal_length: int = 1000
    num_leads: int = 12
    num_workers: int = 2
    val_size: float = 0.1
    random_state: int = 42
    architecture: str = "Custom-1D-CNN-BiLSTM"
    project_name: str = "MediScanX-ECG-Scratch"
    run_name: str = "CNN-BiLSTM-OOP-Refactor"
    data_dir: str = (
        "/kaggle/input/datasets/khyeh0719/ptb-xl-dataset/"
        "ptb-xl-a-large-publicly-available-electrocardiography-dataset-1.0.1/"
    )
    checkpoint_dir: str = "models"
    target_classes: list[str] = field(
        default_factory=lambda: ["NORM", "MI", "STTC", "CD", "HYP"]
    )
    device: torch.device = field(
        default_factory=lambda: torch.device("cuda" if torch.cuda.is_available() else "cpu")
    )


@dataclass
class ECGInferenceConfig:
    """Centralized configuration for ECG inference and Grad-CAM."""

    checkpoint_path: str = (
        "/kaggle/input/datasets/wassamkhan/mediscanx-ecg-weights/"
        "mediscanx-best-ecg-model-epoch12-val_loss0.277.ckpt"
    )
    sample_file_path: str = (
        "/kaggle/input/datasets/khyeh0719/ptb-xl-dataset/"
        "ptb-xl-a-large-publicly-available-electrocardiography-dataset-1.0.1/"
        "records100/04000/04002_lr"
    )
    data_dir: str = (
        "/kaggle/input/datasets/khyeh0719/ptb-xl-dataset/"
        "ptb-xl-a-large-publicly-available-electrocardiography-dataset-1.0.1/"
    )
    sample_rate: int = 100
    seq_length: int = 500
    full_signal_length: int = 1000
    num_leads: int = 12
    heatmap_alpha: float = 0.4
    confidence_threshold: float = 0.5
    target_classes: list[str] = field(
        default_factory=lambda: ["NORM", "MI", "STTC", "CD", "HYP"]
    )
    device: torch.device = field(
        default_factory=lambda: torch.device("cuda" if torch.cuda.is_available() else "cpu")
    )
