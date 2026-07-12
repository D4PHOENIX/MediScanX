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

    # ── Model Paths ──────────────────────────────────────────────────────────
    onnx_model_path: str = Field(default="/models/ecg_v2_12lead.onnx", alias="ECG_ONNX_PATH")
    pytorch_ckpt_path: str = Field(default="/models/ecg_v2_12lead.ckpt", alias="ECG_CKPT_PATH")

    # Keep backwards compatibility aliases if needed
    ecg_onnx_path: str = Field(default="/models/ecg_v2_12lead.onnx")
    ecg_ckpt_path: str = Field(default="/models/ecg_v2_12lead.ckpt")

    # ── Architecture Constants ───────────────────────────────────────────────
    num_leads: int = 12
    seq_length: int = 500
    num_classes: int = 5
    ecg_labels: List[str] = Field(default_factory=lambda: ["NORM", "MI", "STTC", "CD", "HYP"])

    # ── Clinical Decision Boundaries ─────────────────────────────────────────
    classification_threshold: float = 0.5

    # ── Hardware ─────────────────────────────────────────────────────────────
    device: str = "cpu"

    @property
    def torch_device(self) -> torch.device:
        return torch.device("cuda" if torch.cuda.is_available() else self.device)

    # ── Optical Preprocessing (Paper ECG Strip → Signal) ─────────────────────
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

    # ── Explainability ────────────────────────────────────────────────────────
    heatmap_alpha: float = 0.45
    colormap: str = "jet"

    model_config: SettingsConfigDict = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", arbitrary_types_allowed=True, populate_by_name=True
    )