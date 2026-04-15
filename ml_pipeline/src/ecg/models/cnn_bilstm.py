"""
Primary ECG model architecture for MediScanX.
Defines the 1D CNN + BiLSTM model used by the refactored training workflow.
"""

from __future__ import annotations

import pytorch_lightning as pl
import torch
import torch.nn.functional as F
from torch import Tensor, nn
from torchmetrics.classification import MultilabelF1Score

from src.ecg.config import ECGTrainingConfig


class MediScanXECGClassifier(pl.LightningModule):
    """1D CNN + BiLSTM classifier used as the shared ECG architecture."""

    def __init__(self, cfg: ECGTrainingConfig) -> None:
        super().__init__()
        self.save_hyperparameters(ignore=["cfg"])
        self.cfg = cfg

        self.conv1 = nn.Conv1d(cfg.num_leads, 64, kernel_size=5, padding=2)
        self.bn1 = nn.BatchNorm1d(64)
        self.pool1 = nn.MaxPool1d(2)

        self.conv2 = nn.Conv1d(64, 128, kernel_size=5, padding=2)
        self.bn2 = nn.BatchNorm1d(128)
        self.pool2 = nn.MaxPool1d(2)

        self.conv3 = nn.Conv1d(128, 256, kernel_size=3, padding=1)
        self.bn3 = nn.BatchNorm1d(256)
        self.pool3 = nn.MaxPool1d(2)

        self.lstm = nn.LSTM(
            input_size=256,
            hidden_size=128,
            num_layers=2,
            batch_first=True,
            bidirectional=True,
        )
        self.fc1 = nn.Linear(256, 128)
        self.dropout = nn.Dropout(0.4)
        self.fc2 = nn.Linear(128, len(cfg.target_classes))

        self.criterion = nn.BCEWithLogitsLoss()
        self.f1_score = MultilabelF1Score(
            num_labels=len(cfg.target_classes),
            average="macro",
        )

    def extract_features(self, x: Tensor) -> Tensor:
        """Extract convolutional feature maps for classification or Grad-CAM."""

        x = self.pool1(F.relu(self.bn1(self.conv1(x))))
        x = self.pool2(F.relu(self.bn2(self.conv2(x))))
        x = self.pool3(F.relu(self.bn3(self.conv3(x))))
        return x

    def classify_features(self, features: Tensor) -> Tensor:
        """Classify feature maps into ECG pathology logits."""

        sequence_features = features.permute(0, 2, 1)
        sequence_features, _ = self.lstm(sequence_features)
        pooled = torch.mean(sequence_features, dim=1)
        hidden = F.relu(self.fc1(pooled))
        hidden = self.dropout(hidden)
        return self.fc2(hidden)

    def forward(self, x: Tensor) -> Tensor:
        """Run a forward pass on a batched chunked ECG tensor."""

        batch_size, chunks, channels, timesteps = x.shape
        merged = x.view(batch_size * chunks, channels, timesteps)
        features = self.extract_features(merged)
        logits = self.classify_features(features)
        logits = logits.view(batch_size, chunks, -1)
        return torch.mean(logits, dim=1)

    def training_step(self, batch: tuple[Tensor, Tensor], batch_idx: int) -> Tensor:
        """Perform one Lightning training step."""

        del batch_idx
        signals, labels = batch
        logits = self(signals)
        loss = self.criterion(logits, labels)
        self.log("train_loss", loss, prog_bar=True, on_step=False, on_epoch=True)
        return loss

    def validation_step(self, batch: tuple[Tensor, Tensor], batch_idx: int) -> Tensor:
        """Perform one Lightning validation step."""

        del batch_idx
        signals, labels = batch
        logits = self(signals)
        loss = self.criterion(logits, labels)
        self.f1_score(torch.sigmoid(logits), labels.int())
        self.log("val_loss", loss, prog_bar=True, on_step=False, on_epoch=True)
        self.log("val_f1", self.f1_score, prog_bar=True, on_step=False, on_epoch=True)
        return loss

    def configure_optimizers(self) -> torch.optim.Optimizer:
        """Configure the optimizer for Lightning."""

        return torch.optim.Adam(self.parameters(), lr=self.cfg.learning_rate)
