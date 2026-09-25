"""Centralised configuration for the Skin Lesion service.

Uses pydantic-settings to load environment variables from a ``.env`` file.
"""

from dataclasses import dataclass, field
from typing import List, Tuple

import torch
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuration settings for the skin lesion service.

    Attributes:
        skin_weights_path (str): The file path to the model weights. Defaults to "./weights/skin_multidomain_weights.pth".
        device (str): The computation device to use (e.g., "cpu", "cuda"). Defaults to "cpu".
        num_classes (int): The number of classes to predict. Defaults to 8.
        image_size (int): The expected size (width and height) of the input image. Defaults to 224.
    """
    skin_weights_path: str = "./weights/skin_multidomain_weights.pth"
    device: str = "cpu"
    num_classes: int = 8
    image_size: int = 224
    melanoma_triage_threshold: float = 0.20
    enable_otsu_roi: bool = True

    class Config:
        """Pydantic model configuration.

        Attributes:
            env_file (str): The name of the environment file to read.
            env_file_encoding (str): The encoding of the environment file.
        """
        env_file: str = ".env"
        env_file_encoding: str = "utf-8"


@dataclass
class SkinInferenceConfig:
    """Central configuration for the skin-lesion inference service.

    Attributes:
        model_weights_path (str): Filesystem path to the serialised model weights.
        image_size (Tuple[int, int]): Expected ``(height, width)`` for input images.
        num_classes (int): Number of diagnostic classes (8: 7 ISIC pathologies + Normal Skin).
        skin_labels (List[str]): Alphabetically ordered full clinical names.
        skin_abbreviations (List[str]): Corresponding clinical abbreviation codes.
        mean (List[float]): ImageNet channel-wise normalisation mean parameters.
        std (List[float]): ImageNet channel-wise normalisation std parameters.
        melanoma_triage_threshold (float): Clinical safety threshold for melanoma alert (0.20).
        enable_otsu_roi (bool): Enable automated Otsu ROI cropping for uncropped smartphone photos.
        heatmap_alpha (float): Original-image blending weight for Grad-CAM overlay.
        heatmap_beta (float): Heatmap blending weight for Grad-CAM overlay.
        colormap (int): OpenCV colormap identifier (default ``cv2.COLORMAP_JET`` = 2).
        device (torch.device): PyTorch device inferred automatically (cuda / cpu).
    """

    # Filesystem & environment
    model_weights_path: str = "./weights/skin_multidomain_weights.pth"

    # Input / model dimensions 
    image_size: Tuple[int, int] = (224, 224)
    num_classes: int = 8

    # 8-class multi-domain clinical taxonomy (alphabetical matching pd.Categorical)
    skin_labels: List[str] = field(default_factory=lambda: [
        "Actinic keratoses",
        "Basal cell carcinoma",
        "Benign keratosis-like lesions",
        "Dermatofibroma",
        "Melanoma",
        "Normal skin",
        "Melanocytic nevi",
        "Vascular lesions",
    ])

    skin_abbreviations: List[str] = field(default_factory=lambda: [
        "akiec", "bcc", "bkl", "df", "mel", "normal", "nv", "vasc",
    ])

    # ImageNet preprocessing constants 
    mean: List[float] = field(
        default_factory=lambda: [0.485, 0.456, 0.406]
    )
    std: List[float] = field(
        default_factory=lambda: [0.229, 0.224, 0.225]
    )

    # Clinical safety and preprocessing controls
    melanoma_triage_threshold: float = 0.20
    enable_otsu_roi: bool = True

    # Grad-CAM rendering controls 
    heatmap_alpha: float = 0.5
    heatmap_beta: float  = 0.5
    colormap: int = 2  # cv2.COLORMAP_JET

    # Compute device 
    device: torch.device = field(
        default_factory=lambda: torch.device(
            "cuda" if torch.cuda.is_available() else "cpu"
        )
    )
