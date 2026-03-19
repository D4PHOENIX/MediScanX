
"""
Centralized configuration module for the Chest X-Ray (CXR) pipeline.
Defines hyperparameter dataclasses to ensure type safety and eliminate magic numbers.
"""

import os
import torch
from dataclasses import dataclass, field

# Optimize OpenCV for multi-threading in PyTorch DataLoader
cv2_threads = 0
os.environ["OMP_NUM_THREADS"] = "1"

@dataclass
class CXRTrainingConfig:
    """
    Centralized configuration for the Chest X-Ray CIHMLC training pipeline.
    """
    # Project Info
    project_name: str = 'MediScanX-CXR-Init'
    run_name: str = 'DenseNet121-CIHMLC-70-15-15-T4'

    # Data Paths
    kaggle_dataset_root: str = "/kaggle/input/datasets/ashery/chexpert"
    kaggle_data_root: str = "/tmp/chexpert"
    csv_train_path: str = f"{kaggle_data_root}/train.csv"
    csv_valid_path: str = f"{kaggle_data_root}/valid.csv"
    
    # DataLoader Configs
    batch_size: int = 128
    num_workers: int = 4
    image_size: tuple[int, int] = (320, 320)
    
    # Model Architecture
    backbone: str = 'DenseNet121'
    num_classes: int = 14
    pretrained: bool = True
    
    # Training Hyperparameters
    epochs: int = 40
    learning_rate: float = 1e-4
    patience: int = 5
    penalty_weight: float = 1.5
    log_steps: int = 500
    weight_decay: int = 1e-4
    
    # Data Split Parameters
    train_size: float = 0.7
    val_size: float = 0.15
    test_size: float = 0.15
    random_seed: int = 42
    
    

    # Standard CheXpert labels in exact categorical order
    CHEXPERT_LABELS: list[str] = field(default_factory=lambda: [
        "No Finding", "Enlarged Cardiomediastinum", "Cardiomegaly", "Lung Opacity",
        "Lung Lesion", "Edema", "Consolidation", "Pneumonia", "Atelectasis", 
        "Pneumothorax", "Pleural Effusion", "Pleural Other", "Fracture", "Support Devices"
    ])

    # Clinical Taxonomy (Parent Index -> Child Index)
    # Enforces multi-level hierarchical rules based on the CheXpert schema:
    # 1: 'Enlarged Cardiomediastinum' -> 2: 'Cardiomegaly'
    # 3: 'Lung Opacity' -> 4: 'Lung Lesion', 5: 'Edema', 6: 'Consolidation', 8: 'Atelectasis'
    # 6: 'Consolidation' -> 7: 'Pneumonia'
    HIERARCHY_PAIRS: list[tuple[int, int]] = field(default_factory=lambda: [
        (1, 2),
        (3, 4),
        (3, 5),
        (3, 6),
        (3, 8),
        (6, 7)
    ])
    
    # Hardware
    device: torch.device = field(
        default_factory=lambda: torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    )    

@dataclass
class CXRInferenceConfig:
    """Centralized configuration for the Chest X-Ray inference and explainability pipeline."""
    # Paths
    model_weights_path: str = "/kaggle/input/notebooks/d4phoenix/01-cxr-densenet-cihmlc/best_densenet_cihmlc.pth"
    kaggle_dataset_root: str = "/kaggle/input/datasets/ashery/chexpert"
    csv_test_path: str = "/kaggle/input/notebooks/d4phoenix/01-cxr-densenet-cihmlc/temp_splits/test_split.csv"
    
    # Architecture
    image_size: tuple[int, int] = (320, 320)
    num_classes: int = 14 
    pretrained: bool = False
    
    # Interpretability Settings
    heatmap_alpha: float = 0.6
    heatmap_beta: float = 0.4
    colormap: int = cv2.COLORMAP_JET
    
    # Clinical Decision Boundaries
    confidence_threshold: float = 0.5
    
    # Standard CheXpert labels in exact categorical order
    CHEXPERT_LABELS: list[str] = field(default_factory=lambda: [
        "No Finding", "Enlarged Cardiomediastinum", "Cardiomegaly", "Lung Opacity",
        "Lung Lesion", "Edema", "Consolidation", "Pneumonia", "Atelectasis", 
        "Pneumothorax", "Pleural Effusion", "Pleural Other", "Fracture", "Support Devices"
    ])
    
    # Hardware
    device: torch.device = field(
        default_factory=lambda: torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    )