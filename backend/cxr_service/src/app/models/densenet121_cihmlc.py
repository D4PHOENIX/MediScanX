"""DenseNet-121 CIHMLC architecture for hierarchical multi-label CXR classification."""

from typing import Tuple, Any, Optional

import torch
import torch.nn as nn
import torchvision.models as models


class SEBlock(nn.Module):
    """Squeeze-and-Excitation block for channel-wise attention.

    Recalibrates channel responses by modelling inter-channel dependencies: it
    squeezes spatial information into a per-channel descriptor, learns
    per-channel excitation weights, and rescales the input feature map.

    Attributes:
        squeeze (nn.AdaptiveAvgPool2d): Global average pool that collapses each channel to a scalar.
        excitation (nn.Sequential): Bottleneck MLP producing per-channel gating weights in
            ``[0, 1]``.
    """

    def __init__(self, channels: int, reduction: int = 16) -> None:
        """Initialize the Squeeze-and-Excitation block.

        Args:
            channels (int): Number of input (and output) feature channels.
            reduction (int): Channel-reduction ratio of the excitation bottleneck.
        """
        super().__init__()
        self.squeeze: nn.AdaptiveAvgPool2d = nn.AdaptiveAvgPool2d(1)
        self.excitation: nn.Sequential = nn.Sequential(
            nn.Linear(channels, channels // reduction, bias=False),
            nn.ReLU(inplace=True),
            nn.Linear(channels // reduction, channels, bias=False),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Apply channel-wise recalibration to the input feature map.

        Args:
            x (torch.Tensor): Input feature map of shape ``[B, C, H, W]``.

        Returns:
            torch.Tensor: The input rescaled by the learned per-channel weights, same shape
            as ``x``.
        """
        b: int
        c: int
        b, c, _, _ = x.size()
        y: torch.Tensor = self.squeeze(x).view(b, c)
        y = self.excitation(y).view(b, c, 1, 1)
        return x * y.expand_as(x)


class DenseNet121_CIHMLC(nn.Module):
    """Clinically-Inspired Hierarchical Multi-Label Classification model.

    Uses a DenseNet-121 backbone and extracts the raw 1024-channel spatial
    feature maps from the final dense block to enable precise Grad-CAM++
    localization without intermediate convolutional bottlenecks. An SE block
    recalibrates the features before global pooling and classification.

    Attributes:
        features (nn.Sequential): DenseNet-121 feature-extractor blocks.
        relu (nn.ReLU): Standalone activation (kept as a module for PTQ fusion).
        se_block (SEBlock): Channel-wise attention over the 1024-channel maps.
        global_avg_pool (nn.AdaptiveAvgPool2d): Collapses ``(H, W)`` to ``(1, 1)``.
        dropout (nn.Dropout): Regularization before the classifier head.
        classifier (nn.Linear): Maps the 1024 features to the class logits.
    """

    def __init__(self, num_classes: int = 14, pretrained: bool = False) -> None:
        """Initialize the DenseNet121_CIHMLC architecture.

        Args:
            num_classes (int): Number of output diagnostic labels. Defaults to 14;
                the CIHMLC weights use 20 (14 base + 6 hierarchical).
            pretrained: Whether to initialize the backbone with ImageNet
                weights. Defaults to ``False``.
        """
        super().__init__()

        weights: Optional[Any] = models.DenseNet121_Weights.DEFAULT if pretrained else None
        densenet: models.DenseNet = models.densenet121(weights=weights)

        self.features: nn.Sequential = densenet.features

        # ReLU kept as a standalone module so PyTorch quantization can fuse the
        # final BatchNorm2d (norm5) with it during INT8 conversion.
        self.relu: nn.ReLU = nn.ReLU(inplace=False)
        self.se_block: SEBlock = SEBlock(channels=1024, reduction=16)

        self.global_avg_pool: nn.AdaptiveAvgPool2d = nn.AdaptiveAvgPool2d((1, 1))
        self.dropout: nn.Dropout = nn.Dropout(p=0.5)
        self.classifier: nn.Linear = nn.Linear(in_features=1024, out_features=num_classes)

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """Execute the dual-output forward pass.

        Args:
            x (torch.Tensor): Batch of 3-channel X-ray images of shape ``[B, 3, H, W]``.

        Returns:
            Tuple[torch.Tensor, torch.Tensor]: A tuple ``(logits, spatial_features)`` where ``logits`` has shape
            ``[B, num_classes]`` and ``spatial_features`` has shape
            ``[B, 1024, H', W']``. The spatial features are the SE-recalibrated
            maps hooked by Grad-CAM++.
        """
        # DenseNet's native features end with a BatchNorm2d (norm5); apply the
        # explicit ReLU to obtain the activated spatial maps used by Grad-CAM++.
        x_features: torch.Tensor = self.features(x)
        spatial_features: torch.Tensor = self.relu(x_features)
        spatial_features = self.se_block(spatial_features)

        pooled: torch.Tensor = self.global_avg_pool(spatial_features)
        flattened: torch.Tensor = torch.flatten(pooled, 1)
        flattened = self.dropout(flattened)
        logits: torch.Tensor = self.classifier(flattened)

        return logits, spatial_features
