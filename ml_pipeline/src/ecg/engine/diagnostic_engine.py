"""
Core orchestration layer for ECG diagnostic inference.
Coordinates preprocessing, model prediction, and Grad-CAM visualization.
"""

from __future__ import annotations

import os
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from torch import nn

from src.ecg.config import ECGInferenceConfig
from src.ecg.data.preprocessor import ECGPreprocessor
from src.ecg.utils.explainability import GradCAM1D


class ECGInferenceEngine:
    """Inference engine that combines preprocessing, prediction, and Grad-CAM visualization."""

    def __init__(
        self,
        cfg: ECGInferenceConfig,
        model: nn.Module,
        preprocessor: ECGPreprocessor,
        gradcam: GradCAM1D,
    ) -> None:
        self.cfg = cfg
        self.model = model.to(cfg.device)
        self.preprocessor = preprocessor
        self.gradcam = gradcam

    def run(self, file_path: str, target_class_idx: int, lead_idx: int = 1) -> dict[str, Any]:
        """Run one ECG inference pass and package the Grad-CAM result."""

        input_tensor, raw_signal = self.preprocessor.process(file_path)
        input_tensor = input_tensor.to(self.cfg.device)
        heatmaps, logits = self.gradcam.generate_heatmap(input_tensor, target_class_idx)
        probabilities = sigmoid_tensor(logits[0])

        return {
            "raw_signal": raw_signal,
            "heatmaps": heatmaps,
            "probabilities": probabilities,
            "target_class_idx": target_class_idx,
            "target_label": self.cfg.target_classes[target_class_idx],
            "lead_idx": lead_idx,
            "patient_id": os.path.basename(file_path),
        }

    def visualize(self, results: dict[str, Any], chunk_idx: int = 0) -> None:
        """Render the ECG signal and corresponding Grad-CAM strip for a specific chunk."""

        lead_idx = int(results["lead_idx"])
        target_label = str(results["target_label"])
        patient_id = str(results["patient_id"])
        confidence = float(results["probabilities"][int(results["target_class_idx"])])

        # Explicitly slice the signal to match the chosen chunk index
        start_idx = chunk_idx * self.cfg.seq_length
        end_idx = start_idx + self.cfg.seq_length
        signal_chunk = results["raw_signal"][start_idx:end_idx, lead_idx]
        
        heatmap = results["heatmaps"][chunk_idx]

        # Dynamic time axis based on configuration
        duration_s = self.cfg.seq_length / self.cfg.sampling_rate
        time_axis = np.linspace(0, duration_s, self.cfg.seq_length)
        
        fig, axis = plt.subplots(figsize=(12, 4))
        axis.plot(time_axis, signal_chunk, color="black", linewidth=1.5, label="ECG Signal")

        ymin, ymax = axis.get_ylim()
        axis.imshow(
            heatmap[np.newaxis, :],
            cmap="jet",
            aspect="auto",
            alpha=self.cfg.heatmap_alpha,
            extent=[0, duration_s, ymin, ymax],
        )

        axis.set_title(
            f"MediScanX 1D Grad-CAM | Patient: {patient_id} | Target: {target_label} | "
            f"Confidence: {confidence * 100:.1f}% | Chunk: {chunk_idx}",
            fontsize=14,
            fontweight="bold",
        )
        axis.set_xlabel("Time (Seconds)", fontsize=12)
        axis.set_ylabel("Amplitude (mV)", fontsize=12)
        axis.legend(loc="upper right")

        color_mapper = plt.cm.ScalarMappable(cmap="jet", norm=plt.Normalize(vmin=0, vmax=1))
        colorbar = fig.colorbar(color_mapper, ax=axis, pad=0.02)
        colorbar.set_label("Neural Network Attention", rotation=270, labelpad=15)
        plt.tight_layout()
        plt.show()


def sigmoid_tensor(logits: np.ndarray) -> np.ndarray:
    """Apply sigmoid to a 1D NumPy logits array."""

    return 1.0 / (1.0 + np.exp(-logits))