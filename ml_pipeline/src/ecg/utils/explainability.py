"""
Explainability utilities for ECG inference.
Implements 1D Grad-CAM for waveform-level feature attribution.
"""

from __future__ import annotations

import numpy as np
import pytorch_lightning as pl
import torch
import torch.nn.functional as F
from torch import Tensor, nn

from src.ecg.config import ECGInferenceConfig


class GradCAM1D:
    """Hook-based 1D Grad-CAM implementation for ECG feature attribution."""

    def __init__(self, cfg: ECGInferenceConfig, model: pl.LightningModule, target_layer: nn.Module) -> None:
        self.cfg = cfg
        self.model = model
        self.target_layer = target_layer
        self.gradients: Tensor | None = None
        self.activations: Tensor | None = None

        self._forward_hook_handle = self.target_layer.register_forward_hook(self._save_activation)
        self._backward_hook_handle = self.target_layer.register_full_backward_hook(self._save_gradient)
    def remove_hooks(self) -> None:
        """Detach registered hooks from the target layer."""
        if self._forward_hook_handle is not None:
            self._forward_hook_handle.remove()
            self._forward_hook_handle = None
        if self._backward_hook_handle is not None:
            self._backward_hook_handle.remove()
            self._backward_hook_handle = None
    def close(self) -> None:
        """Release hook resources associated with this Grad-CAM instance."""
        self.remove_hooks()
    def __enter__(self) -> "GradCAM1D":
        """Support context-manager usage for automatic hook cleanup."""
        return self
    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        """Remove hooks when leaving a context-manager scope."""
        del exc_type, exc_value, traceback
        self.close()

    def _save_activation(self, module: nn.Module, inputs: tuple[Tensor, ...], output: Tensor) -> None:
        """Store the latest forward activations."""

        del module, inputs
        self.activations = output.detach()

    def _save_gradient(
        self,
        module: nn.Module,
        grad_input: tuple[Tensor | None, ...],
        grad_output: tuple[Tensor, ...],
    ) -> None:
        """Store the latest backward gradients."""

        del module, grad_input
        self.gradients = grad_output[0].detach()

    def generate_heatmap(self, input_tensor: Tensor, target_class_idx: int) -> tuple[np.ndarray, np.ndarray]:
        """Generate chunk-level normalized Grad-CAM heatmaps."""

        self.model.eval()
        self.model.zero_grad()
        previous_cudnn = torch.backends.cudnn.enabled
        torch.backends.cudnn.enabled = False

        try:
            cloned_input = input_tensor.clone().detach().requires_grad_(True)
            # Handle both model signatures (single Tensor or tuple/list)
            model_output = self.model(cloned_input)
            logits = model_output[0] if isinstance(model_output, (tuple, list)) else model_output
            score = logits[0, target_class_idx]
            score.backward()
        finally:
            torch.backends.cudnn.enabled = previous_cudnn

        if self.gradients is None or self.activations is None:
            raise RuntimeError("Grad-CAM hooks did not capture gradients or activations.")

        weights = torch.mean(self.gradients, dim=2, keepdim=True)
        cam = torch.sum(weights * self.activations, dim=1)
        cam = F.relu(cam)

        cam = cam.unsqueeze(1)
        cam_resized = F.interpolate(
            cam,
            size=self.cfg.seq_length,
            mode="linear",
            align_corners=False,
        ).squeeze(1)

        for index in range(cam_resized.shape[0]):
            cam_resized[index] -= torch.min(cam_resized[index])
            max_value = torch.max(cam_resized[index])
            if max_value > 0:
                cam_resized[index] /= max_value

        return cam_resized.cpu().numpy(), logits.detach().cpu().numpy()
