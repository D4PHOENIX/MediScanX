"""1‑D Grad‑CAM explainability engine."""

from __future__ import annotations

import logging
from typing import Any, Optional, Tuple, Type

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

# Force non-interactive Agg backend before any pyplot import.
# Must be at module level — calling matplotlib.use() after pyplot has been
# imported is a silent no-op in matplotlib >= 3.3.
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from app.core.config import Settings

logger: logging.Logger = logging.getLogger(__name__)


class GradCAM1D:
    """1-D Grad‑CAM for time‑series explainability.

    Lifecycle
    ---------
    Use as a context manager to automatically register / unregister hooks
    and disable CuDNN during the Grad‑CAM computation (required because
    the bidirectional LSTM can deadlock during ``backward()`` inside
    ``.eval()`` mode with CuDNN enabled).

    Example
    -------
    >>> with GradCAM1D(cfg, model, target_layer) as gradcam:
    ...     heatmap = gradcam.generate_heatmap(input_tensor, target_idx)
    ...     overlay = gradcam.render_overlay(signal, heatmap, "I")

    Attributes:
        cfg (Settings): Engine configuration.
        model (nn.Module): The classification model.
        target_layer (nn.Module): The target convolutional layer.
        feature_maps (Optional[torch.Tensor]): Hooked feature maps.
        gradients (Optional[torch.Tensor]): Hooked gradients.
    """

    def __init__(
        self,
        cfg: Settings,
        model: nn.Module,
        target_layer: Optional[nn.Module] = None,
    ) -> None:
        """Initialise the engine but do **not** register hooks yet.

        Args:
            cfg (Settings): Inference configuration (device, seq_length, …).
            model (nn.Module): PyTorch ECG model (must be an ``ECGClassifier``
                or compatible).
            target_layer (Optional[nn.Module]): The conv layer to hook for feature maps and
                gradients. Defaults to ``model.conv3``.

        Raises:
            ValueError: If target_layer is None and model lacks 'conv3' attribute.
        """
        self.cfg: Settings = cfg
        self.model: nn.Module = model
        self.target_layer: nn.Module = target_layer or getattr(self.model, "conv3", None)
        if self.target_layer is None:
            raise ValueError(
                "target_layer not provided and model has no attribute 'conv3'"
            )

        # Registered hook handles (set in __enter__, cleared in __exit__)
        self._forward_handle: Optional[torch.utils.hooks.RemovableHandle] = None
        self._backward_handle: Optional[torch.utils.hooks.RemovableHandle] = None

        # Cached feature maps / gradients from the hook callbacks
        self.feature_maps: Optional[torch.Tensor] = None
        self.gradients: Optional[torch.Tensor] = None

    # ------------------------------------------------------------------
    #  Context‑manager protocol
    # ------------------------------------------------------------------

    def __enter__(self) -> "GradCAM1D":
        """Disable CuDNN and register the forward/backward hooks.

        Returns:
            GradCAM1D: The GradCAM instance.
        """
        self._prev_cudnn: bool = torch.backends.cudnn.enabled
        torch.backends.cudnn.enabled = False

        self._forward_handle = self.target_layer.register_forward_hook(
            self._save_feature_maps
        )
        self._backward_handle = self.target_layer.register_full_backward_hook(
            self._save_gradients
        )
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> bool:
        """Restore CuDNN setting and unregister the hooks.

        Args:
            exc_type (Optional[Type[BaseException]]): Exception type.
            exc_val (Optional[BaseException]): Exception value.
            exc_tb (Optional[Any]): Traceback.

        Returns:
            bool: False, propagating any exceptions.
        """
        torch.backends.cudnn.enabled = self._prev_cudnn

        if self._forward_handle is not None:
            self._forward_handle.remove()
            self._forward_handle = None
        if self._backward_handle is not None:
            self._backward_handle.remove()
            self._backward_handle = None
        return False

    # ------------------------------------------------------------------
    #  Hook callbacks
    # ------------------------------------------------------------------

    def _save_feature_maps(
        self,
        module: nn.Module,
        input_tuple: Tuple[torch.Tensor, ...],
        output: torch.Tensor,
    ) -> None:
        """Forward hook callback to save feature maps.

        Args:
            module (nn.Module): The hooked module.
            input_tuple (Tuple[torch.Tensor, ...]): Input tensors.
            output (torch.Tensor): Output tensor.
        """
        self.feature_maps = output

    def _save_gradients(
        self,
        module: nn.Module,
        grad_in: Tuple[torch.Tensor, ...],
        grad_out: Tuple[torch.Tensor, ...],
    ) -> None:
        """Backward hook callback to save gradients.

        Args:
            module (nn.Module): The hooked module.
            grad_in (Tuple[torch.Tensor, ...]): Input gradients.
            grad_out (Tuple[torch.Tensor, ...]): Output gradients.
        """
        self.gradients = grad_out[0]

    # ------------------------------------------------------------------
    #  Grad‑CAM computation
    # ------------------------------------------------------------------

    def generate_heatmap(
        self,
        input_tensor: torch.Tensor,
        target_class_idx: int,
    ) -> np.ndarray:
        """Generate a 1‑D saliency heatmap for a single target class.

        The heatmap is normalised to ``[0, 1]`` and interpolated to
        ``cfg.seq_length`` (typically 500).

        Args:
            input_tensor (torch.Tensor): Pre‑processed signal tensor ``(1, 12, 500)``
                (should already be on the correct device).
            target_class_idx (int): Index of the pathology class of interest.

        Returns:
            np.ndarray: ``(seq_length,)`` numpy array of heatmap intensities.

        Raises:
            RuntimeError: If hooks are not registered or if feature maps
                or gradients were not successfully captured.
        """
        if self._forward_handle is None or self._backward_handle is None:
            raise RuntimeError(
                "GradCAM1D hooks are not registered – "
                "the engine must be used as a context manager."
            )

        self.model.zero_grad()

        # Duplicate and require gradients on the input
        cloned: torch.Tensor = input_tensor.clone().detach().requires_grad_(True)
        logits: torch.Tensor = self.model(cloned)
        score: torch.Tensor = logits[0, target_class_idx]
        score.backward()

        # Protection: if gradients are None (unlikely), raise
        if self.feature_maps is None or self.gradients is None:
            raise RuntimeError(
                "Feature maps or gradients were not captured by hooks."
            )

        # Weight each feature channel by its average gradient over time
        # grads : (1, C, T) – average over temporal axis
        weights: torch.Tensor = torch.mean(self.gradients, dim=2, keepdim=True)  # (1, C, 1)

        cam: torch.Tensor = (weights * self.feature_maps).sum(dim=1)  # (1, T)
        cam = F.relu(cam)

        # Normalise to [0, 1]
        cam_min: torch.Tensor = cam.min()
        cam_max: torch.Tensor = cam.max()
        cam = (cam - cam_min) / (cam_max - cam_min + 1e-8)

        # Interpolate to full sequence length
        cam_4d: torch.Tensor = cam.unsqueeze(1)                         # (1, 1, T)
        cam_4d = F.interpolate(
            cam_4d,
            size=self.cfg.seq_length,
            mode="linear",
            align_corners=False,
        )
        cam_1d: torch.Tensor = cam_4d.squeeze(1).squeeze(0)             # (seq_length)

        return cam_1d.detach().cpu().numpy().astype(np.float32)

    # ------------------------------------------------------------------
    #  Overlay rendering
    # ------------------------------------------------------------------

    def render_overlay(
        self,
        signal_array: np.ndarray,
        heatmap: np.ndarray,
        lead_name: str = "",
    ) -> np.ndarray:
        """Render a clinical‑grade overlay of raw signal + Grad‑CAM heatmap.

        Args:
            signal_array (np.ndarray): 1‑D numpy array of the raw ECG signal for one lead.
            heatmap (np.ndarray): 1‑D numpy array of ``[0,1]`` saliency values
                (output of ``generate_heatmap``).
            lead_name (str): Human‑readable name for the lead (only used for
                logging; not rendered on the plot). Defaults to "".

        Returns:
            np.ndarray: An ``(H, W, 3)`` uint8 RGB image ready for PNG encoding.
        """
        y_min: float = float(signal_array.min())
        y_max: float = float(signal_array.max())
        if y_max == y_min:
            y_max = y_min + 1.0
        pad: float = (y_max - y_min) * 0.05
        y_min -= pad
        y_max += pad

        fig: matplotlib.figure.Figure
        ax: matplotlib.axes.Axes
        fig, ax = plt.subplots(figsize=(6, 2))
        ax.plot(signal_array, color="black", linewidth=1.5)

        # Tile the 1‑D heatmap so imshow can draw it over the full y‑range
        heatmap_2d: np.ndarray = np.tile(heatmap.reshape(1, -1), (100, 1))
        extent: List[float] = [0, len(signal_array) - 1, y_min, y_max]
        ax.imshow(
            heatmap_2d,
            extent=extent,
            aspect="auto",
            cmap="jet",
            alpha=0.45,
            origin="lower",
            interpolation="bilinear",
        )
        ax.set_axis_off()
        fig.tight_layout(pad=0)

        fig.canvas.draw()
        buf: np.ndarray = np.asarray(fig.canvas.buffer_rgba())      # (H, W, 4)
        rgb: np.ndarray = buf[..., :3].copy()                        # discard alpha
        plt.close(fig)

        if lead_name:
            logger.debug("Rendered Grad‑CAM overlay for lead %s.", lead_name)
        return rgb
