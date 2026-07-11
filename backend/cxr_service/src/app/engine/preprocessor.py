"""Deterministic preprocessing pipeline with a bypass for pre-baked images."""

from typing import Tuple, List, Optional

import cv2
import numpy as np
import torch
import torchvision.transforms.functional as TF

from app.core.config import Settings as CXRInferenceConfig
from app.core.exceptions import ImageReadError, ImageProcessingError


class OfflinePreprocessorMirror:
    """Exact mirror of the training-time offline preprocessor.

    Reproduces the deterministic ``crop -> CLAHE -> pad -> resize`` pipeline
    applied to raw radiographs at training time, so inference-time inputs match
    the distribution the model was trained on.

    Attributes:
        crop_threshold (int): Minimum pixel intensity kept by the foreground auto-crop.
        image_size (Tuple[int, int]): Target ``(height, width)`` of the output image.
        clahe_clip_limit (float): Contrast clip limit for CLAHE.
        clahe_tile_grid_size (Tuple[int, int]): Tile grid size for CLAHE.
    """

    def __init__(
        self,
        crop_threshold: int = 15,
        image_size: Tuple[int, int] = (320, 320),
        clahe_clip_limit: float = 3.0,
        clahe_tile_grid_size: Tuple[int, int] = (10, 10),
    ) -> None:
        """Initialize the offline preprocessing mirror.

        Args:
            crop_threshold (int): Minimum pixel intensity kept by the auto-crop.
            image_size (Tuple[int, int]): Target ``(height, width)`` of the output image.
            clahe_clip_limit (float): Contrast clip limit for CLAHE.
            clahe_tile_grid_size (Tuple[int, int]): Tile grid size for CLAHE.
        """
        self.crop_threshold: int = crop_threshold
        self.image_size: Tuple[int, int] = image_size
        self.clahe_clip_limit: float = clahe_clip_limit
        self.clahe_tile_grid_size: Tuple[int, int] = clahe_tile_grid_size

    def _auto_crop(self, img: np.ndarray) -> np.ndarray:
        """Crop the image to the bounding box of its foreground pixels.

        Args:
            img (np.ndarray): Single-channel grayscale image.

        Returns:
            np.ndarray: The cropped image, or the original if no foreground is found.
        """
        mask: np.ndarray = img > self.crop_threshold
        coords: np.ndarray = np.argwhere(mask)
        if coords.size == 0:
            return img
        y0: int
        x0: int
        y1: int
        x1: int
        y0, x0 = coords.min(axis=0)
        y1, x1 = coords.max(axis=0) + 1
        return img[y0:y1, x0:x1]

    def _apply_clahe_and_rgb(self, img: np.ndarray) -> np.ndarray:
        """Apply CLAHE contrast enhancement and convert to 3-channel RGB.

        Args:
            img (np.ndarray): Single-channel grayscale image; normalized to ``uint8`` if it
                is not already.

        Returns:
            np.ndarray: A 3-channel RGB image with enhanced local contrast.
        """
        if img.dtype != np.uint8:
            img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        clahe: cv2.CLAHE = cv2.createCLAHE(clipLimit=self.clahe_clip_limit, tileGridSize=self.clahe_tile_grid_size)
        enhanced: np.ndarray = clahe.apply(img)
        return cv2.cvtColor(enhanced, cv2.COLOR_GRAY2RGB)

    def _pad_to_square(self, img: np.ndarray) -> np.ndarray:
        """Zero-pad the image symmetrically to a square aspect ratio.

        Args:
            img (np.ndarray): Image of shape ``[H, W, C]``.

        Returns:
            np.ndarray: The square-padded image.
        """
        h: int
        w: int
        h, w = img.shape[:2]
        diff: int = abs(h - w)
        pad1: int
        pad2: int
        pad1, pad2 = diff // 2, diff - diff // 2
        if w > h:
            return cv2.copyMakeBorder(img, pad1, pad2, 0, 0, cv2.BORDER_CONSTANT, value=[0, 0, 0])
        return cv2.copyMakeBorder(img, 0, 0, pad1, pad2, cv2.BORDER_CONSTANT, value=[0, 0, 0])

    def __call__(self, img: np.ndarray) -> np.ndarray:
        """Run the full offline pipeline on a raw grayscale image.

        Args:
            img (np.ndarray): Single-channel grayscale radiograph.

        Returns:
            np.ndarray: An RGB ``uint8`` image resized to :attr:`image_size`.
        """
        img_cropped: np.ndarray = self._auto_crop(img)
        img_clahe: np.ndarray = self._apply_clahe_and_rgb(img_cropped)
        img_padded: np.ndarray = self._pad_to_square(img_clahe)
        return cv2.resize(img_padded, self.image_size, interpolation=cv2.INTER_AREA)


class CXRInferencePreprocessor:
    """Deterministic clinical preprocessing with a bypass for baked datasets.

    When ``cfg.is_preprocessed`` is ``True`` the input is assumed already
    clinically processed and only requires resize plus ImageNet normalization;
    otherwise the full :class:`OfflinePreprocessorMirror` pipeline is applied.

    Attributes:
        cfg (CXRInferenceConfig): Inference configuration.
        offline_preprocessor (Optional[OfflinePreprocessorMirror]): Offline pipeline, present only when inputs are raw.
        mean (List[float]): Per-channel ImageNet normalization means.
        std (List[float]): Per-channel ImageNet normalization standard deviations.
    """

    def __init__(self, cfg: CXRInferenceConfig) -> None:
        """Initialize the preprocessor.

        Args:
            cfg (CXRInferenceConfig): Inference configuration controlling the preprocessing mode and
                target image size.
        """
        self.cfg: CXRInferenceConfig = cfg
        self.offline_preprocessor: Optional[OfflinePreprocessorMirror] = None

        if not self.cfg.is_preprocessed:
            self.offline_preprocessor = OfflinePreprocessorMirror(
                crop_threshold=15,
                image_size=cfg.image_size,
                clahe_clip_limit=3.0,
                clahe_tile_grid_size=(10, 10),
            )

        self.mean: List[float] = [0.485, 0.456, 0.406]
        self.std: List[float] = [0.229, 0.224, 0.225]

    def process(self, image_path: str) -> Tuple[torch.Tensor, np.ndarray]:
        """Load and preprocess an image into a model-ready tensor.

        Args:
            image_path (str): Filesystem path to the image to load.

        Returns:
            Tuple[torch.Tensor, np.ndarray]: A tuple ``(batched_tensor, visual_base)`` where ``batched_tensor``
            has shape ``[1, 3, H, W]`` and ``visual_base`` is the RGB ``uint8``
            image used for Grad-CAM++ overlays.

        Raises:
            ImageReadError: If OpenCV cannot decode the image at ``image_path``.
            ImageProcessingError: If other processing errors occur.
        """
        try:
            visual_base: np.ndarray
            if self.cfg.is_preprocessed:
                raw_img: Optional[np.ndarray] = cv2.imread(image_path, cv2.IMREAD_COLOR)
                if raw_img is None:
                    raise ImageReadError(path=image_path)

                visual_base = cv2.cvtColor(raw_img, cv2.COLOR_BGR2RGB)

                if visual_base.shape[:2] != self.cfg.image_size:
                    visual_base = cv2.resize(visual_base, self.cfg.image_size, interpolation=cv2.INTER_AREA)
            else:
                raw_img_gray: Optional[np.ndarray] = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
                if raw_img_gray is None:
                    raise ImageReadError(path=image_path)
                if self.offline_preprocessor is None:
                    raise ImageProcessingError(message="Offline preprocessor is missing.")
                visual_base = self.offline_preprocessor(raw_img_gray)

            base_tensor: torch.Tensor = TF.to_tensor(visual_base)
            normalized_tensor: torch.Tensor = TF.normalize(base_tensor, mean=self.mean, std=self.std)
            batched_tensor: torch.Tensor = normalized_tensor.unsqueeze(0)

            return batched_tensor, visual_base
        except ImageReadError:
            raise
        except Exception as exc:
            raise ImageProcessingError(
                message="Failed to process image.",
                context={"path": image_path, "error": str(exc)},
            ) from exc
