"""
Evaluation and reporting utilities for ECG experiments.
Provides validation visualization helpers for multilabel classification.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
import torch
from sklearn.metrics import multilabel_confusion_matrix
from torch import Tensor
from torch.utils.data import DataLoader

from src.ecg.models.cnn_bilstm import MediScanXECGClassifier


class ECGEvaluationDashboard:
    """Utility class for multilabel confusion-matrix reporting."""

    @staticmethod
    def plot(
        model: MediScanXECGClassifier,
        dataloader: DataLoader[tuple[Tensor, Tensor]],
        class_names: list[str],
        device: torch.device,
    ) -> None:
        """Generate a confusion-matrix figure using validation predictions."""

        model.to(device)
        model.eval()
        all_preds: list[np.ndarray] = []
        all_targets: list[np.ndarray] = []

        with torch.no_grad():
            for signals, labels in dataloader:
                signals = signals.to(device)
                logits = model(signals)
                preds = (torch.sigmoid(logits) > 0.5).int().cpu().numpy()
                all_preds.extend(preds)
                all_targets.extend(labels.int().cpu().numpy())

        preds_array = np.array(all_preds)
        targets_array = np.array(all_targets)
        matrices = multilabel_confusion_matrix(targets_array, preds_array)

        fig, axes = plt.subplots(1, len(class_names), figsize=(28, 6))
        fig.suptitle(
            "MediScanX 1D-CNN + Bi-LSTM: Clinical Evaluation Results (PTB-XL Dataset)",
            fontsize=24,
            fontweight="bold",
            y=1.05,
        )

        tick_labels = ["Negative", "Positive"]
        for axis, matrix, class_name in zip(axes, matrices, class_names):
            sns.heatmap(
                matrix,
                annot=True,
                fmt="d",
                cmap="Blues",
                ax=axis,
                cbar=False,
                annot_kws={"size": 18, "weight": "bold"},
                xticklabels=tick_labels,
                yticklabels=tick_labels,
            )
            axis.set_title(f"Class: {class_name}", fontsize=20, fontweight="bold", pad=15)
            axis.set_xlabel("Predicted by Model", fontsize=16, labelpad=10)
            axis.set_ylabel("Actual Condition", fontsize=16, labelpad=10)
            axis.tick_params(axis="both", which="major", labelsize=14)

        plt.tight_layout()
        plt.show()
