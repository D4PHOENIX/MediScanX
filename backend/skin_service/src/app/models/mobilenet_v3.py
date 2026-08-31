"""Bare MobileNetV3‑Small classifier for the Skin Lesion inference service.

Stripped of all PyTorch Lightning dependencies.  A static factory
method ``from_weights`` handles checkpoint loading and key‑prefix
cleanup (``model.`` from Lightning state dicts).
"""

from collections import OrderedDict
from typing import Any, Dict, Optional

import torch
import torch.nn as nn
from torchvision import models

from app.core.config import SkinInferenceConfig


class SkinClassifier(nn.Module):
    """MobileNetV3‑Small backbone with a custom Linear classification head.
    
    Attributes:
        backbone (torch.nn.Module): The underlying MobileNetV3-Small backbone.
    """

    def __init__(self, num_classes: int = 7) -> None:
        """Initializes the SkinClassifier with a MobileNetV3 backbone.

        Args:
            num_classes (int, optional): The number of output classes. Defaults to 7.
        """
        super().__init__()
        self.backbone: nn.Module = models.mobilenet_v3_small(weights=None)

        in_features: int = self.backbone.classifier[3].in_features  # 1024
        self.backbone.classifier[3] = nn.Linear(in_features, num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Performs a forward pass through the model.
        
        Args:
            x (torch.Tensor): A batch of input images. Expected shape is (B, C, H, W).

        Returns:
            torch.Tensor: Raw logits of shape (B, num_classes).
        """
        return self.backbone(x)

    @staticmethod
    def from_weights(
        weight_path: str,
        cfg: Optional[SkinInferenceConfig] = None,
    ) -> "SkinClassifier":
        """Load a checkpoint (``.pt`` or Lightning ``.ckpt``) into a fresh model.

        The function automatically strips leading ``model.`` prefixes that are
        introduced by ``pytorch_lightning.LightningModule``.

        Args:
            weight_path (str): The file path to the saved model weights.
            cfg (Optional[SkinInferenceConfig], optional): Configuration object containing inference settings. Defaults to None.

        Returns:
            SkinClassifier: The instantiated model loaded with the specified weights.
        """
        if cfg is None:
            cfg = SkinInferenceConfig()

        model: SkinClassifier = SkinClassifier(num_classes=cfg.num_classes)
        # weights_only=True prevents arbitrary pickle execution (security) and
        # suppresses the FutureWarning emitted by PyTorch >= 2.0.
        state_dict: Dict[str, Any] = torch.load(weight_path, map_location="cpu", weights_only=True)

        cleaned: Dict[str, Any] = OrderedDict()
        for k, v in state_dict.items():
            # Lightning stores the backbone under 'model.' – remove it
            clean_key: str = k[6:] if k.startswith("model.") else k
            
            # Map standard torchvision keys to our 'backbone' wrapper
            if clean_key.startswith("features.") or clean_key.startswith("classifier."):
                clean_key = "backbone." + clean_key
                
            cleaned[clean_key] = v

        model.load_state_dict(cleaned, strict=False)
        model.eval()
        model.to(cfg.device)
        return model
