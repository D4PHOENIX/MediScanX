"""
MediScanX: CXR Model Training Entry Point
Binds configurations, data routing, architectures, and the training engine and
executes the DenseNet121 CIHMLC training pipeline using the CheXpert dataset.

"""
import torch
import torch.nn as nn
import torch.optim as optim
import torch._dynamo

# imports from internal packages
from src.cxr.config import CXRTrainingConfig
from src.cxr.data.datamodule import CXRDataModule
from src.cxr.models.densenet121_cihmlc import DenseNet121_CIHMLC
from src.cxr.models.losses import HBCELoss
from src.cxr.utils.metrics import ClassWeightCalculator
from ml_pipeline.src.cxr.engine.trainer import CIHMLCTrainer
from src.core.telemetry import ExperimentTracker

torch._dynamo.config.suppress_errors = True

def main():
    """
    Executes the end-to-end MediScanX Chest X-Ray training pipeline.
    """
    # Initialize Global Configuration
    cfg = CXRTrainingConfig()
    print(f"Executing MediScan CXR Pipeline on: {cfg.device}")
    
    # Initialize MLOps Telemetry
    ExperimentTracker.initialize(cfg)
    
    # Setup Data Routing (Patient-Aware Data Splits and DataLoaders)
    print("Initializing Data Module and performing patient-aware splits...")
    data_module = CXRDataModule(cfg)
    train_loader, val_loader, test_loader = data_module.setup()
    
    # Instantiate Model Architecture
    model = DenseNet121_CIHMLC(num_classes=cfg.num_classes, pretrained=cfg.pretrained)
    
    # Enable multi-GPU support if available
    if torch.cuda.device_count() > 1:
        print(f"Accelerating training across {torch.cuda.device_count()} GPUs!")
        model = nn.DataParallel(model)
        
    model = model.to(cfg.device)
    
    # Compile the model for native C++ kernel fusion
    print("Compiling model via torch.compile()...")
    model = torch.compile(model)
    
    # Initialize Dynamic Loss Function
    # Extract the actual training dataframe from the PyTorch subset to calculate class imbalance
    train_indices = train_loader.dataset.indices
    df_train = train_loader.dataset.dataset.annotations.iloc[train_indices]
    
    pos_weights = ClassWeightCalculator.compute_pos_weights(df_train, num_classes=cfg.num_classes).to_device(cfg.device)
    hbce_criterion = HBCELoss(pos_weights=pos_weights, hierarchy_pairs=cfg.HIERARCHY_PAIRS, penalty_weight=cfg.penalty_weight)
    
    # Optimizer and Scheduler
    optimizer = optim.AdamW(model.parameters(), lr=cfg.learning_rate, weight_decay=cfg.weight_decay)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='max', factor=0.1, patience=2)
    
    # Execute Training Loop
    trainer = CIHMLCTrainer(
        model=model,
        train_loader=train_loader,
        val_loader=val_loader,
        test_loader=test_loader,
        criterion=hbce_criterion,
        optimizer=optimizer,
        scheduler=scheduler,
        config=cfg
    ) 
    
    trainer.execute_training(save_path='densenet_cihmlc.pth')
    
    # Clean up Telemetry
    ExperimentTracker.close()
    
if __name__ == "__main__":
    main()