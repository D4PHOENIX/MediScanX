import torch
import torch.nn as nn
import torchvision.models as models
import pytorch_lightning as pl
from torchmetrics.classification import MulticlassF1Score
from typing import Tuple

from src.skin.config import SkinConfig

class MediScanX_Skin_Baseline(pl.LightningModule):
    """MobileNetV3-Small implementation optimized for edge inference."""
    
    def __init__(self, config: SkinConfig, class_weights: torch.Tensor):
        super().__init__()
        self.save_hyperparameters(ignore=['class_weights'])
        self.config = config
        
        # 1. Load Pre-trained MobileNetV3-Small
        self.model = models.mobilenet_v3_small(weights=models.MobileNet_V3_Small_Weights.DEFAULT)
        
        # 2. Modify Classifier Head for our 7 classes
        in_features = self.model.classifier[3].in_features
        self.model.classifier[3] = nn.Linear(in_features, self.config.num_classes)
        
        # 3. Define Loss & Metrics
        self.criterion = nn.CrossEntropyLoss(weight=class_weights)
        self.train_f1 = MulticlassF1Score(num_classes=self.config.num_classes, average='macro')
        self.val_f1 = MulticlassF1Score(num_classes=self.config.num_classes, average='macro')

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.model(x)

    def training_step(self, batch: Tuple[torch.Tensor, torch.Tensor], batch_idx: int) -> torch.Tensor:
        x, y = batch
        logits = self(x)
        loss = self.criterion(logits, y)
        self.train_f1(logits, y)
        
        self.log("train_loss", loss, on_step=False, on_epoch=True, prog_bar=True)
        self.log("train_f1", self.train_f1, on_step=False, on_epoch=True, prog_bar=True)
        return loss

    def validation_step(self, batch: Tuple[torch.Tensor, torch.Tensor], batch_idx: int) -> torch.Tensor:
        x, y = batch
        logits = self(x)
        loss = self.criterion(logits, y)
        self.val_f1(logits, y)
        
        self.log("val_loss", loss, on_step=False, on_epoch=True, prog_bar=True)
        self.log("val_f1", self.val_f1, on_step=False, on_epoch=True, prog_bar=True)
        return loss

    def configure_optimizers(self):
        optimizer = torch.optim.AdamW(self.parameters(), lr=self.config.lr, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode='min', factor=0.5, patience=2, min_lr=1e-6
        )
        return {"optimizer": optimizer, "lr_scheduler": scheduler, "monitor": "val_loss"}