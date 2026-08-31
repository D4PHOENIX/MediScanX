import base64

import cv2
import numpy as np
import torch
import torch.nn.functional as F

from app.core.exceptions import ModelInferenceError

def encode_image(img: np.ndarray) -> str:
    """Convert a numpy image (RGB uint8) to a base64‑encoded PNG string.
    
    Encodes the generated Grad-CAM++ overlays or original base images into a 
    transmission-ready base64 string for embedding in the JSON response payload.

    Args:
        img (np.ndarray): The input image array in RGB format of shape ``[H, W, 3]``.

    Returns:
        str: The base64-encoded PNG string representation of the image.
    """
    _, buffer = cv2.imencode(".png", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    return base64.b64encode(buffer).decode("utf-8")

def generate_gradcam(
    logits: torch.Tensor,
    spatial_features: torch.Tensor,
    target_idx: int,
) -> np.ndarray:
    """Compute a normalized Grad-CAM++ heatmap for one target class.
    
    Produces class-discriminative visual explanations of the model's diagnostic 
    predictions by highlighting the salient spatial regions in the radiograph that 
    contributed most heavily to the target diagnosis.


    Args:
        logits (torch.Tensor): Raw model logits of shape ``[1, num_classes]`` from a
            grad-tracking forward pass.
        spatial_features (torch.Tensor): Spatial feature maps of shape ``[1, C, H', W']``
            produced by the same forward pass.
        target_idx (int): Index of the class to explain.

    Returns:
        np.ndarray: A ``float`` heatmap of shape ``[H', W']`` normalized to ``[0, 1]``.

    Raises:
        ModelInferenceError: If autograd cannot compute gradients (e.g. the forward
            pass ran under ``torch.no_grad()`` or the graph was freed).
    """
    score: torch.Tensor = logits[0, target_idx]

    try:
        gradients: torch.Tensor = torch.autograd.grad(
            outputs=score,
            inputs=spatial_features,
            retain_graph=True,
        )[0]
    except RuntimeError as e:
        raise ModelInferenceError(
            message="Autograd failed or memory error occurred during Grad-CAM computation.",
            context={"error": str(e)}
        ) from e

    activations: torch.Tensor = spatial_features.detach()
    grad_2: torch.Tensor = gradients.pow(2)
    grad_3: torch.Tensor = gradients.pow(3)

    global_sum: torch.Tensor = activations.sum(dim=(2, 3), keepdim=True) * grad_3
    denominator: torch.Tensor = 2 * grad_2 + global_sum

    denominator = torch.where(
        denominator != 0.0, denominator, torch.ones_like(denominator)
    )

    alphas: torch.Tensor = grad_2 / denominator
    weights: torch.Tensor = (alphas * torch.relu(gradients)).sum(dim=(2, 3), keepdim=True)

    heatmap: torch.Tensor = (weights * activations).sum(dim=1).squeeze()
    heatmap = F.relu(heatmap)
    heatmap_np: np.ndarray = heatmap.cpu().numpy()

    h_min: float
    h_max: float
    h_min, h_max = float(heatmap_np.min()), float(heatmap_np.max())
    if h_max - h_min > 1e-8:
        heatmap_np = (heatmap_np - h_min) / (h_max - h_min)
    else:
        heatmap_np = np.zeros_like(heatmap_np)

    return heatmap_np

def overlay_heatmap(
    visual_base_rgb: np.ndarray,
    heatmap: np.ndarray,
    colormap: int,
    heatmap_beta: float,
) -> np.ndarray:
    """Colorize a heatmap and blend it over the base RGB image.
    
    Creates a human-readable clinical overlay where intense colors (e.g., red) 
    indicate regions of high diagnostic importance for the predicted finding, 
    allowing clinicians to visually verify the model's focus area.


    Args:
        visual_base_rgb (np.ndarray): Base image as an RGB ``uint8`` array of shape
            ``[H, W, 3]``.
        heatmap (np.ndarray): Normalized heatmap of shape ``[H', W']`` in ``[0, 1]``.
        colormap (int): OpenCV colormap (e.g. cv2.COLORMAP_JET).
        heatmap_beta (float): Blend strength for the heatmap.

    Returns:
        np.ndarray: The blended overlay as an RGB ``uint8`` array of shape ``[H, W, 3]``.
    """
    heatmap_rescaled: np.ndarray = cv2.resize(
        heatmap,
        (visual_base_rgb.shape[1], visual_base_rgb.shape[0]),
        interpolation=cv2.INTER_CUBIC,
    )
    heatmap_rescaled = cv2.GaussianBlur(heatmap_rescaled, (11, 11), 0)

    heatmap_uint8: np.ndarray = np.uint8(255 * heatmap_rescaled)
    heatmap_colored_bgr: np.ndarray = cv2.applyColorMap(heatmap_uint8, colormap)
    heatmap_colored_rgb: np.ndarray = cv2.cvtColor(heatmap_colored_bgr, cv2.COLOR_BGR2RGB)

    base_f32: np.ndarray = visual_base_rgb.astype(np.float32)
    heat_f32: np.ndarray = heatmap_colored_rgb.astype(np.float32)

    mask: np.ndarray = heatmap_rescaled[..., np.newaxis]
    effective_alpha: np.ndarray = mask * heatmap_beta

    overlay: np.ndarray = (base_f32 * (1.0 - effective_alpha)) + (heat_f32 * effective_alpha)
    return np.clip(overlay, 0, 255).astype(np.uint8)
