"""Environment-driven settings for the CXR service.

Values are loaded from the process environment (and an optional ``.env`` file)
via ``pydantic-settings``. Environment variable names are matched
case-insensitively to the field names below.
"""

from typing import List, Optional, Tuple
import numpy as np
import torch
from pydantic import Field, ConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the CXR inference container.

    Attributes:
        model_config (SettingsConfigDict): Pydantic model configuration.
        CXR_WEIGHTS_PATH (str): Filesystem path to the DenseNet-121 ``.pth`` weights.
        CXR_THRESHOLDS_PATH (str): Filesystem path to the per-class ``.npy`` decision
            thresholds calibrated at training time.
        image_size (Tuple[int, int]): Target ``(height, width)`` of the model input.
        heatmap_beta (float): Blending strength of the Grad-CAM++ overlay.
        colormap (int): OpenCV colormap id used to colorize heatmaps.
        is_preprocessed (bool): If ``True``, inputs are already clinically baked.
        chexpert_labels (List[str]): The 14 CheXpert base labels in categorical order.
        high_level_labels (List[str]): The 6 hierarchical top-level labels.
        classification_thresholds (Optional[np.ndarray]): Per-class thresholds populated at load time.
    """

    model_config: SettingsConfigDict = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    CXR_WEIGHTS_PATH: str = "/models/weights.pth"
    CXR_THRESHOLDS_PATH: str = "/models/thresholds.npy"

    image_size: Tuple[int, int] = (320, 320)
    heatmap_beta: float = 0.4
    colormap: int = 2  # cv2.COLORMAP_JET

    is_preprocessed: bool = True

    chexpert_labels: List[str] = Field(default_factory=lambda: [
        "No Finding", "Enlarged Cardiomediastinum", "Cardiomegaly", "Lung Opacity",
        "Lung Lesion", "Edema", "Consolidation", "Pneumonia", "Atelectasis",
        "Pneumothorax", "Pleural Effusion", "Pleural Other", "Fracture", "Support Devices",
    ])

    high_level_labels: List[str] = Field(default_factory=lambda: [
        "Abnormal", "Fluid Accumulation", "Missing Lung Tissue", "Other", "Cardiac", "Opacity",
    ])

    classification_thresholds: Optional[np.ndarray] = None

    @property
    def num_classes(self) -> int:
        """Total output classes (base + hierarchical)."""
        return len(self.chexpert_labels) + len(self.high_level_labels)

    @property
    def device(self) -> torch.device:
        """Torch device used for inference (CUDA if available, else CPU)."""
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
