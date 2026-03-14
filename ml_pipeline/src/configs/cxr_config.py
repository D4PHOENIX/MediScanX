from dataclasses import dataclass, asdict
import torch

@dataclass
class CXRConfig:
    """
    Centralized configuration for the Chest X-Ray CIHMLC pipeline.
    
    This dataclass holds all hyperparameters, architectural flags, and hardware 
    settings. Modifying this dictates the behavior of the entire training pipeline.
    """
    # Project Info
    project_name: str = 'MediScanX'
    run_name: str = 'DenseNet121-CIHMLC-70-15-15'

    # Hardware and Data Paths
    device: str = 'cuda' if torch.cuda.is_available() else 'cpu'
    kaggle_data_root: str = "/kaggle/input/datasets/ashery/chexpert"
    csv_train_path: str = f"{kaggle_data_root}/train.csv"
    
    # DataLoader Configs
    batch_size: int = 32
    num_workers: int = 4
    image_size: tuple = (320, 320)
    
    # Model Architecture
    backbone: str = 'DenseNet121'
    num_classes: int = 14
    pretrained: bool = True
    
    # Training Hyperparameters
    epochs: int = 40
    learning_rate: float = 1e-4
    patience: int = 5
    penalty_weight: float = 1.5
    
    # Data Split Parameters
    train_size: float = 0.7
    val_size: float = 0.15
    test_size: float = 0.15
    random_seed: int = 42
