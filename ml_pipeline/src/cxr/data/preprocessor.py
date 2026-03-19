"""
Radiographic preprocessing module for clinical inference.
Imports the base training transformations to guarantee strict architectural parity, 
and applies inference-specific extraction (RGB visual base for Grad-CAM overlays) 
and CPU-side ImageNet normalization.
"""
import cv2
import numpy as np
import torch
import torchvision.transforms.functional as TF

from src.cxr.config import CXRInferenceConfig
from src.cxr.data.transforms import RadiographicPipeline

class CXRInferencePreprocessor:
    """Deterministic clinical preprocessing pipeline for single-image inference."""
    def __init__(self, cfg: CXRInferenceConfig) -> None:
        """
        Initializes the inference preprocessor
        
        Args:
            cfg (CXRInferenceConfig): The global inference configuration object.
        """
        self.cfg = cfg
        self.base_transforms = RadiographicPipeline.get_base_transforms(self.cfg.image_size)
        # ImageNet Normalization Stats (Replicates 'gpu_val_aug' from the training engine)
        self.mean = [0.485, 0.456, 0.406]
        self.std = [0.229, 0.224, 0.225]
        
    def process(self, image_path: str) -> tuple[torch.Tensor, np.ndarray]:
        """
        Applies the exact clinical preprocessing sequence required for model ingestion.

        Args:
            image_path (str): The absolute or relative path to the x-ray image.

        Returns:
            tuple[torch.Tensor, np.ndarray]: 
                - batched_tensor: A 4D model-ready tensor [1, 3, H, W]
                - visual_base: The CLAHE-enhanced RGB Numpy array for Grad-CAM overlays
                
        Raises:
            FileNotFoundError: If the specified image path does not exist or is unreadable.
        """
        raw_img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        
        if raw_img is None:
            raise FileNotFoundError(f"OpenCV could not find or read the image at: {image_path}")
        
        # Phase 1: Base Pipeline (Strict Parity with Training)
        # ApplyCLAHE -> ToTensor -> Resize. Yields a [3, H, W] tensor in range [0.0, 1.0].
        base_tensor = self.base_transforms(raw_img)
        
        # Phase 2: Visual Base Extraction for Dashboard
        # Capture the image state *after* CLAHE and Resize, but *before* ImageNet normalization.
        # Permute from [C, H, W] back to [H, W, C] and scale to 8-bit integer.
        visual_base = (base_tensor.permute(1, 2, 0).numpy() * 255).astype(np.uint8)
        
        # Phase 3: Hardware Augmentation Parity (Normalization)
        # Apply the statistical normalization that was handled on the GPU during training.
        normalized_tensor = TF.normalize(base_tensor, mean=self.mean, std=self.std)
        
        # Phase 4: Add Batch Dimension
        batched_tensor = normalized_tensor.unsqueeze(0)
        
        return batched_tensor, visual_base