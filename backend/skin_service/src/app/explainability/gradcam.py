"""2‑D Grad‑CAM explainability engine for MobileNetV3‑Small."""

from typing import Optional, Any

import cv2
import numpy as np
import torch
import torch.nn as nn

from app.core.config import SkinInferenceConfig


class SkinGradCAM:
    """Lightweight Grad‑CAM implementation ported from the NB1 notebook.

    The class follows the same API as ``cxr_service.engine.gradcam.GradCAMPlusPlus``
    so that the diagnostic engine can consume it identically.

    Lifecycle
    ---------
    **Must** be used as a context manager so that forward/backward hooks are
    registered before ``generate_heatmap`` is called and are cleanly removed
    afterwards.

    Example::

        with SkinGradCAM(cfg, model) as gradcam:
            heatmap = gradcam.generate_heatmap(tensor, class_idx)
            overlay = gradcam.blend_overlay(visual_base_rgb, heatmap)
    """

    def __init__(
        self,
        cfg: SkinInferenceConfig,
        model: nn.Module,
        target_layer: Optional[nn.Module] = None,
    ) -> None:
        """Initializes the SkinGradCAM engine.

        Args:
            cfg (SkinInferenceConfig): Configuration settings.
            model (nn.Module): The underlying PyTorch model.
            target_layer (Optional[nn.Module], optional): The target convolutional layer 
                for Grad-CAM feature extraction. Defaults to the last layer of the backbone.
        """
        self.cfg: SkinInferenceConfig = cfg
        self.model: nn.Module = model
        if target_layer is None:
            # Last convolutional block of the backbone before the classifier
            target_layer = self.model.backbone.features[-1]
        self.target_layer: nn.Module = target_layer

        self._activations: Optional[torch.Tensor] = None
        self._gradients: Optional[torch.Tensor] = None

        # Hook handles — None until __enter__ is called.
        # NOT registered here to avoid the double-registration bug.
        self._forward_handle: Optional[torch.utils.hooks.RemovableHandle] = None
        self._backward_handle: Optional[torch.utils.hooks.RemovableHandle] = None

    # ------------------------------------------------------------------
    #  Context‑manager protocol
    # ------------------------------------------------------------------

    def __enter__(self) -> "SkinGradCAM":
        """Registers forward and backward hooks on the target layer.
        
        Returns:
            SkinGradCAM: The initialized Grad-CAM instance.
        """
        self._forward_handle = self.target_layer.register_forward_hook(
            self._save_activations
        )
        self._backward_handle = self.target_layer.register_full_backward_hook(
            self._save_gradients
        )
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        """Removes hooks when leaving the context.
        
        Args:
            exc_type (Any): Exception type.
            exc_val (Any): Exception value.
            exc_tb (Any): Traceback object.
            
        Returns:
            bool: Always False to propagate exceptions.
        """
        if self._forward_handle is not None:
            self._forward_handle.remove()
            self._forward_handle = None
        if self._backward_handle is not None:
            self._backward_handle.remove()
            self._backward_handle = None
        return False  # propagate exceptions

    # ------------------------------------------------------------------
    #  Hook callbacks
    # ------------------------------------------------------------------

    def _save_activations(
        self,
        module: nn.Module,
        input: torch.Tensor,
        output: torch.Tensor,
    ) -> None:
        """Saves the target layer activations during the forward pass.
        
        Args:
            module (nn.Module): The hooked module.
            input (torch.Tensor): The module input.
            output (torch.Tensor): The module output.
        """
        self._activations = output

    def _save_gradients(
        self,
        module: nn.Module,
        grad_input: tuple,
        grad_output: tuple,
    ) -> None:
        """Saves the target layer gradients during the backward pass.
        
        Args:
            module (nn.Module): The hooked module.
            grad_input (tuple): The input gradients.
            grad_output (tuple): The output gradients.
        """
        # grad_output[0] shape: (B, C, H, W)
        self._gradients = grad_output[0]

    # ------------------------------------------------------------------
    #  Grad‑CAM computation
    # ------------------------------------------------------------------

    def generate_heatmap(
        self,
        input_tensor: torch.Tensor,
        target_class_idx: int,
    ) -> np.ndarray:
        """Compute the standard 2‑D Grad‑CAM heatmap.

        Args:
            input_tensor (torch.Tensor): Already‑preprocessed input of shape ``(1, 3, 224, 224)``.
                The tensor does **not** need ``requires_grad=True`` — this method
                temporarily enables grad computation internally.
            target_class_idx (int): The index of the class to be explained.

        Returns:
            np.ndarray: Heatmap with the same spatial resolution as the feature map
                (H_feat, W_feat), normalised to ``[0, 1]``.
        
        Raises:
            RuntimeError: If hooks have not been registered via context manager.
        """
        if self._forward_handle is None or self._backward_handle is None:
            raise RuntimeError(
                "Hooks have not been registered.  Use SkinGradCAM as a context "
                "manager:\n\n    with SkinGradCAM(cfg, model) as gradcam:\n"
                "        heatmap = gradcam.generate_heatmap(tensor, class_idx)\n"
            )

        grad_enabled_prev: bool = torch.is_grad_enabled()
        torch.set_grad_enabled(True)
        try:
            self.model.zero_grad()

            # Clone + detach so the GradCAM backward doesn't interfere with
            # any outer computation graph (e.g. the probs pass).
            inp: torch.Tensor = input_tensor.clone().detach().requires_grad_(True)
            logits: torch.Tensor = self.model(inp)  # (1, num_classes)

            loss: torch.Tensor = logits[0, target_class_idx]
            loss.backward(retain_graph=False)

            # Clone activations before in-place weighting to prevent overwriting
            # the shared reference stored by the hook.
            activations: torch.Tensor = self._activations.clone()  # (1, C, H, W)
            gradients: torch.Tensor   = self._gradients            # (1, C, H, W)

            assert activations is not None and gradients is not None

            # Channel‑wise average gradient
            pooled_gradients: torch.Tensor = torch.mean(gradients, dim=(0, 2, 3))  # (C,)

            # Weighted combination of activation maps (safe: on a local clone)
            channel: int
            for channel in range(activations.shape[1]):
                activations[:, channel, :, :] *= pooled_gradients[channel]

            heatmap: torch.Tensor = torch.mean(activations, dim=1).squeeze()  # (H, W)
            heatmap = torch.relu(heatmap)
            heatmap_np: np.ndarray = heatmap.cpu().detach().numpy()

            h_max: float = heatmap_np.max()
            if h_max > 1e-8:
                heatmap_np /= h_max
            else:
                heatmap_np = np.zeros_like(heatmap_np)

        finally:
            torch.set_grad_enabled(grad_enabled_prev)

        return heatmap_np

    # ------------------------------------------------------------------
    #  Overlay rendering
    # ------------------------------------------------------------------

    def blend_overlay(
        self,
        visual_base_rgb: np.ndarray,
        heatmap: np.ndarray,
    ) -> np.ndarray:
        """Superimpose the Grad‑CAM heatmap onto the original image.

        Args:
            visual_base_rgb (np.ndarray): Original (unnormalised) RGB image, shape ``(H, W, 3)`` and dtype
                ``float32`` or ``uint8``.
            heatmap (np.ndarray): Heatmap returned by ``generate_heatmap``, shape ``(H_feat, W_feat)``.

        Returns:
            np.ndarray: Overlay image of shape ``(224, 224, 3)``, dtype ``uint8``.
        """
        # Resize heatmap to match the input image
        target_h: int
        target_w: int
        target_h, target_w = visual_base_rgb.shape[:2]
        heatmap_resized: np.ndarray = cv2.resize(
            heatmap, (target_w, target_h), interpolation=cv2.INTER_CUBIC
        )

        heatmap_uint8: np.ndarray = np.uint8(255 * heatmap_resized)
        heatmap_colored_bgr: np.ndarray = cv2.applyColorMap(heatmap_uint8, self.cfg.colormap)
        heatmap_colored_rgb: np.ndarray = cv2.cvtColor(heatmap_colored_bgr, cv2.COLOR_BGR2RGB)

        base_f32: np.ndarray = visual_base_rgb.astype(np.float32)
        heat_f32: np.ndarray = heatmap_colored_rgb.astype(np.float32)

        overlay: np.ndarray = (
            base_f32 * self.cfg.heatmap_alpha
            + heat_f32 * self.cfg.heatmap_beta
        )
        overlay = np.clip(overlay, 0, 255).astype(np.uint8)
        return overlay
