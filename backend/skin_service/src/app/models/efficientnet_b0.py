"""EfficientNet-B0 classifier for the Skin Lesion multi-domain inference service.

Supports clean 360-tensor weights loading with custom 8-class classification head
and full backward compatibility with the existing SkinClassifier API.
"""

from collections import OrderedDict
from typing import Any, Dict, Optional

import torch
import torch.nn as nn
from torchvision import models

from app.core.config import SkinInferenceConfig


class EfficientNetB0Classifier(nn.Module):
    """EfficientNet-B0 backbone with custom 8-class Linear classification head.

    Attributes:
        backbone (torch.nn.Module): The underlying EfficientNet-B0 backbone.
    """

    def __init__(self, num_classes: int = 8, dropout_rate: float = 0.30) -> None:
        """Initializes the EfficientNetB0Classifier.

        Args:
            num_classes (int, optional): The number of output classes. Defaults to 8.
            dropout_rate (float, optional): Dropout probability before classifier. Defaults to 0.30.
        """
        super().__init__()
        self.backbone: nn.Module = models.efficientnet_b0(weights=None)
        in_features: int = self.backbone.classifier[1].in_features  # 1280
        self.backbone.classifier = nn.Sequential(
            nn.Dropout(p=dropout_rate),
            nn.Linear(in_features, num_classes)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Performs a forward pass through the model.

        Args:
            x (torch.Tensor): A batch of input images of shape (B, C, H, W).

        Returns:
            torch.Tensor: Raw logits of shape (B, num_classes).
        """
        return self.backbone(x)

    @staticmethod
    def from_weights(
        weight_path: str,
        cfg: Optional[SkinInferenceConfig] = None,
    ) -> "EfficientNetB0Classifier":
        """Load checkpoint weights into a fresh EfficientNet-B0 model.

        Args:
            weight_path (str): The file path to the saved model weights.
            cfg (Optional[SkinInferenceConfig], optional): Configuration object. Defaults to None.

        Returns:
            EfficientNetB0Classifier: Instantiated model loaded with production weights.
        """
        if cfg is None:
            cfg = SkinInferenceConfig()

        model: EfficientNetB0Classifier = EfficientNetB0Classifier(num_classes=cfg.num_classes)
        state_dict: Dict[str, Any] = torch.load(weight_path, map_location="cpu", weights_only=True)

        cleaned: Dict[str, Any] = OrderedDict()
        for k, v in state_dict.items():
            clean_key = k.replace("model.", "").replace("backbone.", "")
            if not clean_key.startswith("backbone."):
                clean_key = "backbone." + clean_key
            cleaned[clean_key] = v

        missing, unexpected = model.load_state_dict(cleaned, strict=False)
        if missing or unexpected:
            raise RuntimeError(
                f"Incompatible EfficientNet-B0 checkpoint: missing={missing}, unexpected={unexpected}"
            )
        model.eval()
        model.to(cfg.device)
        return model


# Backward compatibility alias
SkinClassifier = EfficientNetB0Classifier
