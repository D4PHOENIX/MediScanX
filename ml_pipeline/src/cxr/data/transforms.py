"""
Deterministic clinical preprocessing pipelines.
Standardizes radiographic inputs (CLAHE, tensor scaling) to prevent train/inference data drift.
"""

import cv2
import numpy as np
from torchvision import transforms

class ApplyCLAHE:
    """
    A custom PyTorch transform that applies Contrast Limited Adaptive Histogram Equalization (CLAHE) to a medical image.
    
    This class standardizes radiographic inputs by normalizing illumination discrepancies and enhancing local contrast 
    within lung fields, mitigating artifacts from legacy X-ray machines.
    """
    
    def __init__(self, clip_limit: float = 2.0, tile_grid_size: tuple[int, int] = (8, 8)) -> None:
        """
        Initializes the ApplyCLAHE transform object.

        Args:
            clip_limit (float): Sets the threshold for contrast limiting.
            tile_grid_size (tuple[int, int]): Sets the grid size for localized equalization.
        """
        self.clip_limit = clip_limit
        self.tile_grid_size = tile_grid_size
        self.clahe = cv2.createCLAHE(clipLimit=self.clip_limit, tileGridSize=self.tile_grid_size)
        
    def __call__(self, img: np.ndarray) -> np.ndarray:
        """
        Executes CLAHE and stacks the output into a 3-channel array for transfer learning.

        Args:
            img (np.ndarray): The input grayscale image array.

        Returns:
            np.ndarray: The contrast-enhanced, 3-channel RGB image array.
            
        Raises:
            TypeError: If the input is not a NumPy array. 
        """
        if not isinstance(img, np.ndarray):
            raise TypeError(f"ApplyCLAHE expects a numpy.ndarray, but got {type(img)}")
        
        # Ensure the image is 8-bit grayscale as required by OpenCV CLAHE
        if img.dtype != np.uint8:
            img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX)
            img = img.astype(np.uint8)
            
        # Apply the CLAHE algorithm
        enhanced_img = self.clahe.apply(img)
        
        # Convert to 3-channel representation directly in OpenCV
        enhanced_img_3c = cv2.cvtColor(enhanced_img, cv2.COLOR_GRAY2RGB)
        
        return enhanced_img_3c
    
    def __repr__(self) -> str:
        """Return a string representation of the transform object."""
        return f"{self.__class__.__name__}(clip_limit={self.clip_limit}, tile_grid_size={self.tile_grid_size})"


class RadiographicPipeline:
    """
    A factory class constructing the base preprocessing pipeline for Chest X-Rays prior to model ingestion.
    Provides a unified transform sequence to ensure parity between training and inference environments.
    """
    
    @staticmethod
    def get_base_transforms(resize_dim: tuple[int, int] = (320, 320)) -> transforms.Compose:
        """
        Constructs the sequence of base transforms including CLAHE, tensor conversion, and resizing.

        Args:
            resize_dim (tuple[int, int]): Target dimensions for the neural network.

        Returns:
            transforms.Compose: The chained PyTorch transformations.
        """
        return transforms.Compose([
            ApplyCLAHE(clip_limit=2.0, tile_grid_size=(8, 8)),
            transforms.ToTensor(),
            transforms.Resize(resize_dim, antialias=True)
        ])