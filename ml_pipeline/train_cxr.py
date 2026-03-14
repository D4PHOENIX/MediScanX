"""
MediScanX: CXR Model Training Entry Point
Executes the DenseNet121 CIHMLC training pipeline using the CheXpert dataset.
"""

import os
import pandas as pd
import torch
import torch.optim as optim
from torch.utils.data import DataLoader
from sklearn.model_selection import GroupShuffleSplit
import wandb
from dataclasses import asdict

# imports form src/ modules
from src.configs.cxr_config import CXRConfig
from src.data.cxr_transforms import RadiographicPipeline
from src.data.cxr_dataset import CheXpertDataset
from src.models.densenet121_cihmlc import DenseNet121_CIHMLC
from src.models.losses import HBCELoss
from src.utils.metrics import ClassWeightCalculator, HIERARCHY_PAIRS
from src.utils.trainer import CIHMLCTrainer

def main():
    # Instantiate the global configuration
    CFG = CXRConfig()
    print(f"Executing MediScanX CXR Pipeline on: {CFG.device}")
    
    # Ensure wandb is authenticated in your environment
    wandb.login(key=wandb_api)
    
    if not os.path.exists(CFG.csv_train_path):
        print(f"Dataset missing at {CFG.csv_train_path}. Aborting.")
        return
    
    # Patient-Aware 70/15/15 Split
    print("Executing patient-aware data splitting...")
    df_full = pd.read_csv(CFG.csv_train_path)
    df_full['Patient_ID'] = df_full['Path'].apply(lambda x: x.split('/')[2])
    
    # Split 1: Train and Temp (Val + Test) 
    gss1 = GroupShuffleSplit(n_splits=1, train_size=CFG.train_size, random_state=CFG.random_seed)
    train_idx, temp_idx = next(gss1.split(df_full, groups=df_full['Patient_ID']))
    
    df_train = df_full.iloc[train_idx].copy()
    df_temp = df_full.iloc[temp_idx].copy()
    
    # Split 2: 50% Val, 50% Test from the Temp Set
    gss2 = GroupShuffleSplit(n_splits=1, train_size=0.5, random_state=CFG.random_seed)
    val_idx, test_idx = next(gss2.split(df.temp, groups=df_temp['Patient_ID']))
    
    df_val = df_temp.iloc[val_idx].copy()
    df_test = df_temp.iloc[test_idx].copy()
    
    # Save splits temporarily for the Dataset class to load
    temp_dir = './temp_splits'
    os.makedirs(temp_dir, exist_ok=True)
    df_train.to_csv(f'{temp_dir}/train_split.csv', index=False)
    df_val.to_csv(f'{temp_dir}/val_split.csv', index=False)
    df_test.to_csv(f'{temp_dir}/test_split.csv', index=False)
    
    # Initialize DataLoaders
    cxr_transforms = RadiographicPipeline.get_training_transforms(resize_dim=CFG.image_size)
    
    train_dataset = CheXpertDataset(f'{temp_dir}/train_split.csv', CFG.kaggle_data_root, transform=cxr_transforms)
    val_dataset = CheXpertDataset(f'{temp_dir}/val_split.csv', CFG.kaggle_data_root, transform=cxr_transforms)
    test_dataset = CheXpertDataset(f'{temp_dir}/test_split.csv', CFG.kaggle_data_root, transform=cxr_transforms)
    
    train_loader = DataLoader(train_dataset, batch_size=CFG.batch_size, shuffle=True, num_workers=CFG.num_workers)
    val_loader = DataLoader(val_dataset, batch_size=CFG.batch_size, shuffle=False, num_workers=CFG.num_workers)
    test_loader = DataLoader(test_dataset, batch_size=CFG.batch_size, shuffle=False, num_workers=CFG.num_workers)
    
    # Initialize WandB
    wandb.init(
        project=CFG.project_name,
        name=CFG.run_name,
        config=asdict(CFG)
    )
    
    # Architecture, Loss, and Optimizer Setup
    model = DenseNet121_CIHMLC(num_classes=CFG.num_classes, pretrained=CFG.pretrained).to_device(CFG.device)
    
    pos_weights = ClassWeightCalculator.compute_pos_weights(df_train, num_classes=CFG.num_classes).to(CFG.device)
    hbce_criterion = HBCELoss(pos_weight=pos_weights, hierarchy_pairs=HIERARCHY_PAIRS, penalty_weight=CFG.penalty_weight)
    
    optimizer = optim.Adam(model.parameters(), lr=CFG.learning_rate)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='max', factor=0.1, patience=2)
    
    # Execute Training
    trainer = CIHMLCTrainer(
        model=model, train_loader=train_loader, val_loader=val_loader, test_loader=test_loader,
        criterion=hbce_criterion, optimizer=optimizer, scheduler=scheduler, config=CFG
    )
    
    trainer.execute_training(save_path="best_densenet_cihmlc.pth")
    wandb.finish()

if __name__ == "__main__";
    main()