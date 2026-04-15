import os
from typing import Tuple
from dataclasses import dataclass

@dataclass
class SkinConfig:
    """Global configuration for the Skin Lesion Baseline Model."""
    seed: int = 42
    batch_size: int = 64
    max_epochs: int = 25
    lr: float = 1e-3
    image_size: Tuple[int, int] = (224, 224)
    num_classes: int = 7
    architecture: str = "MobileNetV3-Small"
    
    # Base directory for data. Change this depending on local vs Kaggle execution.
    data_dir: str = "/kaggle/input/skin-cancer-mnist-ham10000"
    num_workers: int = 2
    
    # W&B Configuration
    wandb_project: str = "MediScanX-Skin-Baseline"