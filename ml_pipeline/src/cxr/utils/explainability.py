"""
Mathematical Interpretability Engine for Explainable AI (XAI).
Implements an adaptive, stateless Grad-CAM++ algorithm utilizing higher-order 
gradients. Features Smart Alpha Masking and Adaptive Inversion to highlight 
both positive evidence and counter-evidence based on model confidence.
"""
import cv2
import numpy as np
import torch
import torch.nn.functional as F

from src.cxr.config.inference_config import CXRInferenceConfig

class GradCAMPlusPlus:
    """
    Adaptive Grad-CAM++ Engine for clinical diagnostic explainability.
    
    Synthesizes higher-order gradients and spatial feature maps to generate 
    precise diagnostic heatmaps. Automatically inverts gradient flow for 
    low-confidence predictions to highlight Counter-Evidence.
    """
    def __init__(self, cfg: CXRInferenceConfig) -> None:
        """
        Initializes the GradCAM++ visualizer with blending configurations.

        Args:
            cfg (CXRInferenceConfig): The global inference configuration containing visual weights.
        """
        self.cfg = cfg
        
    def generate_heatmap(self, logits: torch.Tensor, spatial_features: torch.Tensor, target_idx: int) -> np.ndarray:
        """
        Computes a pixel-wise Grad-CAM++ heatmap using 2nd and 3rd order gradients.
        
        Args:
            logits (torch.Tensor): Raw model output scores [1, num_classes].
            spatial_features (torch.Tensor): Spatial maps from the model [1, C, H, W].
            target_idx (int): The index of the clinical pathology to be explained.

        Returns:
            np.ndarray: A normalized 2D heatmap [0.0 to 1.0] representing importance.
        """
        # Isolate the logits score and calculate absolute probability
        score = logits[0, target_idx]
        prob = torch.sigmoid(score).item()
        
        # Extract first-order gradients using stateless autograd
        try:
            gradients = torch.autograd.grad(
                outputs=score,
                inputs=spatial_features,
                retain_graph=True
            )[0]
        except RuntimeError as e:
            raise RuntimeError(
                "Autograd failed. Ensure 'requires_grad=True' was set for inputs and "
                "inference was not performed inside a 'torch.no_grad()' block." 
            ) from e
            
        # If the model is confident the disease is ABSENT (< 50%), we flip the gradients.
        if prob < 0.50:
            gradients = -gradients
            
        # Higher Order Derivatives
        activations = spatial_features.detach()
        grad_2 = gradients.pow(2)
        grad_3 = gradients.pow(3)
        
        # Calculate the denominator for the alpha weights using the original scaling behavior
        global_sum = activations * grad_3.sum(dim=(2, 3), keepdim=True)
        denominator = 2 * grad_2 + global_sum
        
        # Avoid division by zero for numerical stability
        denominator = torch.where(denominator != 0.0, denominator, torch.ones_like(denominator))
        
        # Calculate the pixel-level importance weights (alphas)
        alphas = grad_2 / denominator
        
        # Global Channel Weights calculation using ReLU'd gradients
        weights = (alphas * torch.relu(gradients)).sum(dim=(2, 3), keepdim=True)
        
        # Generate Linear Combination heatmap
        heatmap = (weights * activations).sum(dim=1).squeeze()
        
        # Apply ReLU to retain only positive spatial influence
        heatmap = F.relu(heatmap)
        heatmap_np = heatmap.cpu().numpy()
        
        # Apply Min-Max Normalization to scale values precisely between [0.0, 1.0]
        h_min, h_max = heatmap_np.min(), heatmap_np.max()
        if h_max - h_min > 1e-8:
            heatmap_np = (heatmap_np - h_min) / (h_max - h_min)
        else:
            heatmap_np = np.zeros_like(heatmap_np)
            
        return heatmap_np
    
    def blend_overlay(self, visual_base_rgb: np.ndarray, heatmap: np.ndarray) -> np.ndarray:
        """
        Resizes and blends the mathematical heatmap over the grayscale X-ray using Smart Alpha.

        Args:
            visual_base_rgb (np.ndarray): The CLAHE-enhanced RGB base image.
            heatmap (np.ndarray): The 2D importance map [0.0 to 1.0].

        Returns:
            np.ndarray: A color image with the heatmap blended over the anatomy.
        """
        # Upsample heatmap to match the 320x320 original radiographic resolution
        heatmap_rescaled = cv2.resize(heatmap, (visual_base_rgb.shape[1], visual_base_rgb.shape[0]))
        
        # Apply pseudocolor mapping (JET converts 0 to dark blue)
        heatmap_uint8 = np.uint8(255 * heatmap_rescaled)
        heatmap_colored_bgr = cv2.applyColorMap(heatmap_uint8, self.cfg.colormap)
        heatmap_colored_rgb = cv2.cvtColor(heatmap_colored_bgr, cv2.COLOR_BGR2RGB)
        
        # Convert images to float32 for precise mathematical blending
        base_f32 = visual_base_rgb.astype(np.float32)
        heat_f32 = heatmap_colored_rgb.astype(np.float32)
        
        # Create the dynamic mask based on the raw heatmap activation intensity [0.0, 1.0]
        mask = heatmap_rescaled[..., np.newaxis] 
        
        # If activation is 0.0, effective_alpha is 0.0 (fully transparent).
        # If activation is 1.0, effective_alpha is 0.4 (configured opacity).
        effective_alpha = mask * self.cfg.heatmap_beta
        
        # Mathematical Blending: (Base * (1 - Alpha)) + (Heatmap * Alpha)
        overlay = (base_f32 * (1.0 - effective_alpha)) + (heat_f32 * effective_alpha)
        
        # Clip safely back to 8-bit integer space
        return np.clip(overlay, 0, 255).astype(np.uint8)
    
print("Adaptive Grad-CAM++ Interpretability Engine Initialized.")