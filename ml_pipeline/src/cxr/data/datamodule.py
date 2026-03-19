"""
Data orchestration and routing module.
Enforces patient-aware data splitting to prevent anatomical data leakage across evaluation boundaries.
"""
from torch.utils.data import DataLoader, Subset
from sklearn.model_selection import GroupShuffleSplit
from typing import Tuple
from src.cxr.config import CXRTrainingConfig
from src.cxr.data.transforms import RadiographicPipeline
from src.cxr.data.dataset import CheXpertDataset

class CXRDataModule:
    """
    Orchestrates the instantiation and routing of datasets and dataloaders.
    
    Enforces strict patient-level grouping during the train/val/test split to prevent 
    anatomical data leakage across evaluation boundaries.
    """
    
    def __init__(self, cfg: CXRTrainingConfig) -> None:
        """
        Initializes the CXRDataModule with the global configuration.

        Args:
            cfg (CXRTrainingConfig): The centralized configuration object.
        """
        self.cfg = cfg
        self.base_transforms = RadiographicPipeline.get_base_transforms(self.cfg.image_size)
        
    def setup(self) -> Tuple[DataLoader, DataLoader, DataLoader]:
        """
        Constructs the datasets, performs the patient-aware splits, and builds the dataloaders.

        Returns:
            Tuple[DataLoader, DataLoader, DataLoader]: The train, validation, and test dataloaders.
        """
        # Instantiate the full dataset with CPU-bound deterministic transforms
        full_dataset = CheXpertDataset(
            csv_file=self.cfg.csv_train_path,
            root_dir=self.cfg.kaggle_data_root,
            transform=self.base_transforms
        )
        
        # Extract Patient IDs to act as isolation groups
        # CheXpert paths look like: 'chexpert/train/patient00001/study1/view1_frontal.jpg'
        # Splitting by '/' and taking index 2 reliably extracts the 'patientXXXXX' string
        groups = full_dataset.annotations['Path'].apply(lambda x: x.split('/')[2]).values
        
        # First Split: Isolate Training data from Evaluation data (Val + Test combined)
        eval_size = self.cfg.val_size + self.cfg.test_size
        gss_train_eval = GroupShuffleSplit(n_splits=1, test_size=eval_size, random_state=self.cfg.random_seed)
        
        train_idx, eval_idx = next(gss_train_eval.split(full_dataset.annotations, groups=groups))
        
        # Second Split: Divide the Evaluation pool into Validation and Test sets
        test_ratio = self.cfg.test_size / eval_size
        eval_groups = groups[eval_idx]
        gss_val_test = GroupShuffleSplit(n_splits=1, test_size=test_ratio, random_state=self.cfg.random_seed)
        
        val_idx_relative, test_idx_relative = next(gss_val_test.split(eval_idx, groups=eval_groups))
        
        # Map relative evaluation indices back to the absolute original dataset indices
        val_idx = eval_idx[val_idx_relative]
        test_idx = eval_idx[test_idx_relative]
        
        # Construct PyTorch Subsets
        train_dataset = Subset(full_dataset, train_idx)
        val_dataset = Subset(full_dataset, val_idx)
        test_dataset = Subset(full_dataset, test_idx)
        
        # Build High-Performance DataLoaders
        train_loader = DataLoader(
            train_dataset,
            batch_size=self.cfg.batch_size,
            shuffle=True, # Shuffles batches, but patients remain strictly in the training set
            num_workers=self.cfg.num_workers,
            pin_memory=True if self.cfg.device.type == 'cuda' else False,
            drop_last=True
        )
        
        val_loader = DataLoader(
            val_dataset,
            batch_size=self.cfg.batch_size,
            shuffle=False,
            num_workers=self.cfg.num_workers,
            pin_memory=True if self.cfg.device.type == 'cuda' else False,
            drop_last=False
        )
        
        test_loader = DataLoader(
            test_dataset,
            batch_size=self.cfg.batch_size,
            shuffle=False,
            num_workers=self.cfg.num_workers,
            pin_memory=True if self.cfg.device.type == 'cuda' else False,
            drop_last=False
        )
        
        print(f"Split complete. Train: {len(train_dataset)} | Val: {len(val_dataset)} | Test: {len(test_dataset)}")
        return train_loader, val_loader, test_loader