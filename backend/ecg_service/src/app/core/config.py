"""Centralised configuration for the ECG service.

Uses pydantic‑settings to load environment variables from a ``.env`` file.
"""

from typing import List

import numpy as np
import torch
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings and configuration.

    This class defines configuration variables loaded from the environment
    or a ``.env`` file using pydantic-settings.
    """

    # Model Paths 
    onnx_model_path: str = Field(default="/models/ecg_v2_12lead.onnx", alias="ECG_ONNX_PATH")
    
    # ------------------------------------------------------------------
    # Model parameters — matched to 3rd Experimentation architecture
    # (PTB-XL 100 Hz, 2.5-second windows, 5 superclasses)
    # ------------------------------------------------------------------
    seq_length: int = Field(
        default=250,
        description="Temporal sequence length (250 samples = 2.5 s @ 100 Hz).",
    )
    num_leads: int = Field(default=12, description="Number of ECG leads.")
    num_classes: int = Field(
        default=5,
        description="Number of output diagnostic superclasses.",
    )
    ecg_labels: List[str] = Field(
        default_factory=lambda: ["NORM", "MI", "STTC", "CD", "HYP"],
        description="ECG diagnostic superclass labels in model output order.",
    )
    ecg_thresholds: List[float] = Field(
        default_factory=lambda: [0.49, 0.38, 0.47, 0.49, 0.46],
        description="Per-class calibrated classification thresholds (Notebook 04b, Fold 9).",
    )
    classification_threshold: float = Field(
        default=0.5,
        description="Fallback classification threshold for individual binary decisions.",
    )

    # ------------------------------------------------------------------
    # Weights / Artefacts
    # ------------------------------------------------------------------
    ecg_onnx_path: str = Field(
        default="/models/mediscanx_ecg_3rdexp_finetuned.onnx",
        description="Path to the ONNX runtime model binary.",
    )
    ecg_ckpt_path: str = Field(
        default="/models/mediscanx_ecg_3rdexp_finetuned.ckpt",
        description="Path to the PyTorch Lightning checkpoint file.",
    )
    pytorch_ckpt_path: str = Field(
        default="/models/mediscanx_ecg_3rdexp_finetuned.ckpt",
        alias="ECG_CKPT_PATH",
        description="Alias for ecg_ckpt_path to support legacy test assertions.",
    )

    # Hardware
    device: str = "cpu"

    @property
    def torch_device(self) -> torch.device:
        return torch.device("cuda" if torch.cuda.is_available() else self.device)

    # Optical Preprocessing (Paper ECG Strip → Signal)
    hsv_lower_pink1: np.ndarray = Field(default_factory=lambda: np.array([0, 20, 50], dtype=np.uint8))
    hsv_upper_pink1: np.ndarray = Field(default_factory=lambda: np.array([15, 255, 255], dtype=np.uint8))
    hsv_lower_pink2: np.ndarray = Field(default_factory=lambda: np.array([160, 20, 50], dtype=np.uint8))
    hsv_upper_pink2: np.ndarray = Field(default_factory=lambda: np.array([180, 255, 255], dtype=np.uint8))

    grid_rows: int = 3
    grid_cols: int = 4
    usable_height_ratio: float = 0.75
    lead_layout: List[List[str]] = Field(
        default_factory=lambda: [
            ["I",   "aVR", "V1", "V4"],
            ["II",  "aVL", "V2", "V5"],
            ["III", "aVF", "V3", "V6"],
        ]
    )

    # Explainability
    heatmap_alpha: float = 0.45
    colormap: str = "jet"

    # Diagnostics
    ecg_diagnostic_mode: bool = False
    ecg_diagnostic_dir: str = "/app/data/ecg_diagnostics"

    model_config: SettingsConfigDict = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", arbitrary_types_allowed=True, populate_by_name=True
    )
