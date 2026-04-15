import os
import torch
import numpy as np
import pandas as pd
import pytorch_lightning as pl
from torch.utils.data import DataLoader
import torchvision.transforms as transforms
from typing import Optional, Tuple, Dict
from sklearn.model_selection import train_test_split
from sklearn.utils.class_weight import compute_class_weight

from src.skin.config import SkinConfig
from src.skin.data.dataset import HAM10000Dataset

class SkinDataModule(pl.LightningDataModule):
    """PyTorch Lightning DataModule handling HAM10000 metadata, splits, and dataloaders."""
    
    def __init__(self, config: SkinConfig):
        super().__init__()
        self.config = config
        self.train_df = None
        self.val_df = None
        self.class_weights = None
        self.idx_to_class = None
        
        # Training Augmentations
        self.train_transform = transforms.Compose([
            transforms.Resize(self.config.image_size),
            transforms.RandomHorizontalFlip(),
            transforms.RandomVerticalFlip(),
            transforms.RandomRotation(45),
            transforms.ColorJitter(brightness=0.1, contrast=0.1, saturation=0.1),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        ])
        
        # Validation Transforms
        self.val_transform = transforms.Compose([
            transforms.Resize(self.config.image_size),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        ])

    def prepare_data(self):
        """Finds files and maps metadata. Called only on 1 GPU."""
        csv_path = None
        # Auto-search for metadata
        for dirname, _, filenames in os.walk(self.config.data_dir):
            for filename in filenames:
                if filename == "HAM10000_metadata.csv":
                    csv_path = os.path.join(dirname, filename)
                    break
            if csv_path:
                break
                
        if not csv_path:
            raise FileNotFoundError("Could not find HAM10000_metadata.csv.")
            
        df = pd.read_csv(csv_path)
        
        # Auto-search for images
        image_paths = {}
        for dirname, _, filenames in os.walk(self.config.data_dir):
            for filename in filenames:
                if filename.endswith('.jpg'):
                    image_id = os.path.splitext(filename)[0]
                    image_paths[image_id] = os.path.join(dirname, filename)
                    
        df['path'] = df['image_id'].map(image_paths.get)
        self.full_df = df.dropna(subset=['path'])

    def setup(self, stage: Optional[str] = None):
        """Splits data and calculates weights. Called on every GPU."""
        lesion_type_dict = {
            'nv': 'Melanocytic nevi', 'mel': 'Melanoma', 'bkl': 'Benign keratosis-like lesions',
            'bcc': 'Basal cell carcinoma', 'akiec': 'Actinic keratoses', 
            'vasc': 'Vascular lesions', 'df': 'Dermatofibroma'
        }
        
        self.full_df['cell_type'] = self.full_df['dx'].map(lesion_type_dict)
        self.full_df['target'] = pd.Categorical(self.full_df['cell_type']).codes
        self.idx_to_class = dict(enumerate(pd.Categorical(self.full_df['cell_type']).categories))
        
        # Compute class weights for imbalanced data
        class_weights_arr = compute_class_weight(
            class_weight='balanced',
            classes=np.unique(self.full_df['target']),
            y=self.full_df['target']
        )
        self.class_weights = torch.tensor(class_weights_arr, dtype=torch.float32)
        
        # Stratified 90/10 Split
        self.train_df, self.val_df = train_test_split(
            self.full_df, test_size=0.1, stratify=self.full_df['target'], random_state=self.config.seed
        )
        
        if stage == 'fit' or stage is None:
            self.train_dataset = HAM10000Dataset(self.train_df, transform=self.train_transform)
            self.val_dataset = HAM10000Dataset(self.val_df, transform=self.val_transform)

    def train_dataloader(self) -> DataLoader:
        return DataLoader(self.train_dataset, batch_size=self.config.batch_size,
                          shuffle=True, num_workers=self.config.num_workers, pin_memory=True)

    def val_dataloader(self) -> DataLoader:
        return DataLoader(self.val_dataset, batch_size=self.config.batch_size,
                          shuffle=False, num_workers=self.config.num_workers, pin_memory=True)