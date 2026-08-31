"""Deterministic inference‑time preprocessing for skin lesion images.

Returns both the normalised tensor required by the model and the
un‑normalised RGB visual base array used for Grad‑CAM overlays.
"""

from typing import Tuple, List

import numpy as np
import torch
import torchvision.transforms.functional as TF
from PIL import Image, UnidentifiedImageError

from app.core.config import SkinInferenceConfig
from app.core.exceptions import UnreadableImageFormatError, InvalidImageDimensionError


class SkinPreprocessor:
    """Applies standard ImageNet transforms and provides overlay‑ready data.

    Attributes:
        cfg (SkinInferenceConfig): Configuration settings.
        image_size (Tuple[int, int]): The target image size for resizing.
        mean (List[float]): Normalization mean.
        std (List[float]): Normalization standard deviation.
    """

    def __init__(self, cfg: SkinInferenceConfig) -> None:
        """Initializes the SkinPreprocessor.

        Args:
            cfg (SkinInferenceConfig): The configuration settings.
        """
        self.cfg: SkinInferenceConfig = cfg
        self.image_size: Tuple[int, int] = cfg.image_size  # (224, 224)
        self.mean: List[float] = cfg.mean
        self.std: List[float] = cfg.std

    def process(self, image_path: str) -> Tuple[torch.Tensor, np.ndarray]:
        """Load, resize, normalise and return the batched tensor and visual base array.
        
        Args:
            image_path (str): The file path to the input image.

        Returns:
            Tuple[torch.Tensor, np.ndarray]: A tuple containing:
                - The preprocessed image tensor of shape (1, C, H, W).
                - The unnormalized RGB image array as a NumPy array.

        Raises:
            UnreadableImageFormatError: If the image cannot be read or identified.
            InvalidImageDimensionError: If the processed tensor dimensions do not match the expected size.
        """
        try:
            img: Image.Image = Image.open(image_path).convert("RGB")
        except UnidentifiedImageError as e:
            raise UnreadableImageFormatError(path=image_path) from e
        except Exception as e:
            raise UnreadableImageFormatError(path=image_path) from e

        # visual base (un‑normalised RGB) 
        # antialias=True matches the behaviour of the training-time transforms
        resized: Image.Image = TF.resize(img, list(self.image_size), antialias=True)
        visual_base: np.ndarray = np.array(resized, dtype=np.uint8)  # (H, W, 3)

        # normalised tensor for inference 
        tensor: torch.Tensor = TF.to_tensor(resized)  # [0,1] float32, (C, H, W)
        tensor = TF.normalize(tensor, mean=self.mean, std=self.std)
        batched: torch.Tensor = tensor.unsqueeze(0)  # (1, C, H, W)
        
        if batched.shape[2:] != tuple(self.image_size):
            raise InvalidImageDimensionError(message=f"Expected shape {self.image_size}, got {batched.shape[2:]}")

        return batched, visual_base
