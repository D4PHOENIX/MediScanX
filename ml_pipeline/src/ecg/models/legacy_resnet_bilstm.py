"""
Legacy ECG Grad-CAM model compatibility layer.
Defines the older residual architecture used by pre-refactor explainability checkpoints.
"""

from __future__ import annotations

import pytorch_lightning as pl
import torch.nn.functional as F
from torch import Tensor, nn

from src.ecg.config import ECGInferenceConfig


class Res1DBlock(nn.Module):
    """Residual 1D block used by the legacy ECG Grad-CAM checkpoint."""

    def __init__(self, in_channels: int, out_channels: int, stride: int = 1) -> None:
        super().__init__()
        self.conv1 = nn.Conv1d(
            in_channels,
            out_channels,
            kernel_size=5,
            padding=2,
            stride=stride,
        )
        self.bn1 = nn.BatchNorm1d(out_channels)
        self.conv2 = nn.Conv1d(out_channels, out_channels, kernel_size=5, padding=2)
        self.bn2 = nn.BatchNorm1d(out_channels)

        self.shortcut = nn.Sequential()
        if stride != 1 or in_channels != out_channels:
            self.shortcut = nn.Sequential(
                nn.Conv1d(in_channels, out_channels, kernel_size=1, stride=stride),
                nn.BatchNorm1d(out_channels),
            )

    def forward(self, x: Tensor) -> Tensor:
        """Execute the residual forward pass."""

        residual = self.shortcut(x)
        x = F.relu(self.bn1(self.conv1(x)))
        x = self.bn2(self.conv2(x))
        x += residual
        return F.relu(x)


class LegacyGradCAMECGClassifier(pl.LightningModule):
    """Legacy residual ECG architecture compatible with older Grad-CAM checkpoints."""

    def __init__(self, cfg: ECGInferenceConfig) -> None:
        super().__init__()
        self.cfg = cfg

        self.initial_conv = nn.Sequential(
            nn.Conv1d(cfg.num_leads, 64, kernel_size=7, padding=3, stride=2),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.MaxPool1d(kernel_size=3, stride=2, padding=1),
        )
        self.res_block1 = Res1DBlock(64, 128, stride=2)
        self.res_block2 = Res1DBlock(128, 256, stride=2)

        self.lstm = nn.LSTM(
            input_size=256,
            hidden_size=128,
            num_layers=2,
            batch_first=True,
            bidirectional=True,
        )
        self.fc1 = nn.Linear(256, 128)
        self.dropout = nn.Dropout(0.3)
        self.fc2 = nn.Linear(128, len(cfg.target_classes))

    def extract_features(self, x: Tensor) -> Tensor:
        """Extract residual feature maps from the ECG signal."""

        x = self.initial_conv(x)
        x = self.res_block1(x)
        x = self.res_block2(x)
        return x

    def classify_features(self, features: Tensor) -> Tensor:
        """Map residual features into clinical logits."""

        sequence_features = features.permute(0, 2, 1)
        sequence_features, _ = self.lstm(sequence_features)
        pooled = sequence_features.mean(dim=1)
        hidden = F.relu(self.fc1(pooled))
        hidden = self.dropout(hidden)
        return self.fc2(hidden)

    def forward(self, x: Tensor) -> tuple[Tensor, Tensor]:
        """Run inference and return both logits and feature maps."""

        batch_size, chunks, channels, timesteps = x.shape
        merged = x.view(batch_size * chunks, channels, timesteps)
        features = self.extract_features(merged)
        logits = self.classify_features(features)
        logits = logits.view(batch_size, chunks, -1)
        chunk_logits = logits.mean(dim=1)
        return chunk_logits, features
