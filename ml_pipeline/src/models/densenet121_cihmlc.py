import torch
import torch.nn as nn
import torchvision.models as models

class DenseNet121_CIHMLC(nn.Module):
    """
    Clinically-Inspired Hierarchical Multi-Label Classification Model.
    
    Utilizes a DenseNet121 backbone optimized for feature reuse. The architecture is
    heavily modified with a custom convolutional head and a dual-output forward pass
    to enable offline Explainable AI (Grad-CAM++) on mobile edge devices.

    Args:
        features (nn.Sequential): The pretrained DenseNet121 feature extractor.
        custom_conv (nn.Conv2d): Dimensionality reduction and fine structural extraction layer.
        relu (nn.ReLU): Non-linear activation for the custom conv layer.
        global_avg_pool (nn.AdaptiveAvgPool2d): GAP layer to preserve spatial context.
        classifier (nn.Linear): The final dense layer mapping to the 14 clinical pathologies.
    """
    def __init__(self, num_classes: int=14, pretrained: bool=True):
        """
        Initializes the DenseNet121_CIHMLC architecture.

        Args:
            num_classes (int, optional): The number of output diagnostic labels. Defaults to 14.
            pretrained (bool, optional): Whether to initialize the ImageNet weights. Defaults to True.
        """
        super(DenseNet121_CIHMLC, self).__init__()
        
        # Load the foundation DenseNet121 backbone
        weights = models.DenseNet121_Weights.DEFAULT if pretrained else None
        densenet = models.densenet121(weights=weights)
        
        # Extract the feature blocks
        self.features = densenet.features
        
        # Append Custom Conv2D Layer
        # DenseNet121's feature extractor naturally outputs 1024 channels.
        # We compress this to 512 filters to extract finer structural details and reduce parameters
        self.custom_conv = nn.Conv2d(
            in_channels=1024,
            out_channels=512,
            kernel_size=3,
            padding=1,
            bias=False
        )
        # BatchNorm and ReLU for stabilization and non-linearity
        self.bn = nn.BatchNorm2d(512)
        self.relu = nn.ReLU(inplace=True)
        
        # Global Average Pooling: Condenses the spatial dimensions (H,W) to (1,1) while preserving the 512 feature maps
        self.global_avg_pool = nn.AdaptiveAvgPool2d((1, 1))
        
        # Final Classification layer
        self.classifier = nn.Linear(in_features=512, out_features=num_classes)
        
    def forward(self, x: torch.Tensor) -> tuple:
        """
        Executes the dual-output forward pass.

        Args:
            x (torch.Tensor): A batch of 3-channel X-ray images. Shape: [B, 3, H, W]

        Returns:
            tuple: 
                - logits (torch.Tensor): The raw, unactivated classification scores. Shape: [B, 14]
                - spatial_features (torch.Tensor): The raw spatial maps for Grad-CAM++. Shape: [B, 512, H', W']
        """
        # Pass through the deep DenseNet blocks
        x = self.features(x)
        
        # Pass through the custom structural extraction head
        spatial_features = self.relu(self.bn(self.custom_conv(x)))
        
        # Pool, flatten and classify
        pooled = self.global_avg_pool(spatial_features)
        flattened = torch.flatten(pooled, 1)
        logits = self.classifier(flattened)
        
        # Return both artifacts for the inference engine
        return logits, spatial_features