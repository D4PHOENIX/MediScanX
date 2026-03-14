import cv2
import numpy as np
import torch
from torchvision import transforms
class ApplyCLAHE(object):
    """
    A custom PyTorch transform that applies Contrast Limited Adaptive Histogram Equalization (CLAHE) to a medical image.
    
    This class standardizes radiographic inputs by normalizing illumination discrepancies and enhancing local contrast 
    within lung fields, mitigating artifacts  from legacy X-ray machines.
    
    Attributes:
        clip_limit(float): Threshold for contrast limiting.
        tile_grid_size (tuple): Size of the grid for histogram equalization.
        clahe(cv3.CLAHE): The instantiated OpenCV CLAHE object.
    """
    
    def __init__(self, clip_limit: float=2.0, tile_grid_size: tuple=(8,8)):
        """
        Initializes the ApplyCLAHE transform object.

        Args:
            clip_limit (float, optional): Sets the threshold for contrast limiting. Defaults to 2.0.
            tile_grid_size (tuple, optional): Sets the grid size for localized equalization. Defaults to (8,8).
        """
        self.clip_limit = clip_limit
        self.tile_grid_size = tile_grid_size
        self.clahe = cv2.createCLAHE(clipLimit=self.clip_limit, tileGridSize=self.tile_grid_size)
        
    def __call__(self, img: np.ndarray) -> np.ndarray:
        """
        Executes CLAHE and stacks the output into a 3-channel array for transfer learning.

        Args:
            img (np.ndarray): The input image array.

        Returns:
            np.ndarray: The contrast-enhanced, 3-channel image array.
            
        Raises:
            TypeError: If the input is not a NumPy array. 
        """
        if not isinstance(img, np.ndarray):
            raise TypeError(f"ApplyCLAHE expects a numpy.ndarray, but got{type(img)}")
        
        # Ensure the image is 8-bit grayscale as equired by OpenCV CLAHE
        if img.dtype != np.uint8:
            img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX)
            img = img.astype(np.uint8)
            
            
        # Apply the CLAHE algorithm
        enhanced_img = self.clahe.apply(img)
        enhanced_img_3c = cv2.cvtColor(enhanced_img, cv2.COLOR_GRAY2RGB)
        
        return enhanced_img_3c
    
    def __repr__(self) -> str:
        """Return a string representation of the transform object."""
        return f"{self.__class__.__name__}(clip_limit={self.clip_limit}, tile_grid_size={self.tile_grid_size})"
    
class RadiographicPipeline:
    """
    A factory class to construct the complete preprocessing pipeline for Chest X-Rays prior to model ingestion.
    """
    @staticmethod
    def get_training_transforms(resize_dim: tuple=(320, 320)) -> transforms.Compose:
        """
        Constructs the sequence of transforms including CLAHE, resizing and tensor conversion.
        Args:
            resize_dim (tuple, optional): Target dimensions for the neural network. Defaults to (320,320).

        Returns:
            transforms.Compose: The chained PyTorch transformations.
        """
        return transforms.Compose([
            ApplyCLAHE(clip_limit=2.0, tile_grid_size=(8, 8)),
            transforms.toPILImage(),
            transforms.Resize(resize_dim),
            transforms.ToTensor(),
            # Normalize using full 3-channel ImageNet stats
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        ])