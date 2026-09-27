"""Deterministic inference-time preprocessing for skin lesion images.

Includes automated Otsu ROI bounding box extraction for uncropped smartphone photos
and standard antialiased resizing for close-up clinical dermoscopy.
"""

from typing import Tuple, List

import cv2
import numpy as np
import torch
import torchvision.transforms.functional as TF
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import SkinInferenceConfig
from app.core.exceptions import UnreadableImageFormatError, InvalidImageDimensionError


class SkinPreprocessor:
    """Applies automated ROI extraction, ImageNet normalization, and overlay formatting.

    Attributes:
        cfg (SkinInferenceConfig): Configuration settings.
        image_size (Tuple[int, int]): Target image dimensions for resizing.
        mean (List[float]): Normalization mean.
        std (List[float]): Normalization standard deviation.
        enable_otsu_roi (bool): Whether to auto-crop smartphone macro photos.
    """

    def __init__(self, cfg: SkinInferenceConfig) -> None:
        """Initializes the SkinPreprocessor."""
        self.cfg: SkinInferenceConfig = cfg
        self.image_size: Tuple[int, int] = cfg.image_size
        self.mean: List[float] = cfg.mean
        self.std: List[float] = cfg.std
        self.enable_otsu_roi: bool = getattr(cfg, "enable_otsu_roi", True)

    def extract_lesion_roi(self, pil_img: Image.Image) -> Image.Image:
        """Automatically detect lesion bounding box on uncropped smartphone photos.

        If the image is an uncropped smartphone photo with large surrounding background skin,
        uses Otsu thresholding on the grayscale channel to locate the primary lesion contour,
        applies a 20% margin, and crops. If the lesion already dominates the frame (dermoscopy),
        returns the original image.
        """
        np_img = np.array(pil_img)
        h, w = np_img.shape[:2]

        gray = cv2.cvtColor(np_img, cv2.COLOR_RGB2GRAY)
        blurred = cv2.GaussianBlur(gray, (7, 7), 0)

        _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        opening = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=2)

        contours, _ = cv2.findContours(opening, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return pil_img

        largest_cnt = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest_cnt)
        total_area = h * w

        # Only apply crop if the lesion occupies between 2% and 60% of frame (typical smartphone photo)
        if 0.02 * total_area < area < 0.60 * total_area:
            x, y, cw, ch = cv2.boundingRect(largest_cnt)
            margin_x = int(cw * 0.20)
            margin_y = int(ch * 0.20)
            x1 = max(0, x - margin_x)
            y1 = max(0, y - margin_y)
            x2 = min(w, x + cw + margin_x)
            y2 = min(h, y + ch + margin_y)
            return pil_img.crop((x1, y1, x2, y2))

        return pil_img

    def process(self, image_path: str) -> Tuple[torch.Tensor, np.ndarray]:
        """Load, crop ROI, resize, normalise and return the batched tensor and visual base array."""
        try:
            img: Image.Image = Image.open(image_path).convert("RGB")
            img = ImageOps.exif_transpose(img)
        except UnidentifiedImageError as e:
            raise UnreadableImageFormatError(path=image_path) from e
        except Exception as e:
            raise UnreadableImageFormatError(path=image_path) from e

        # Apply automated ROI extraction for smartphone photos if enabled
        if self.enable_otsu_roi:
            img = self.extract_lesion_roi(img)

        # Visual base (un-normalised RGB for Grad-CAM overlays)
        resized: Image.Image = TF.resize(img, list(self.image_size), antialias=True)
        visual_base: np.ndarray = np.array(resized, dtype=np.uint8)

        # Normalised tensor for inference
        tensor: torch.Tensor = TF.to_tensor(resized)
        tensor = TF.normalize(tensor, mean=self.mean, std=self.std)
        batched: torch.Tensor = tensor.unsqueeze(0)

        if batched.shape[2:] != tuple(self.image_size):
            raise InvalidImageDimensionError(message=f"Expected shape {self.image_size}, got {batched.shape[2:]}")

        return batched, visual_base
