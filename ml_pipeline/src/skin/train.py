import pytorch_lightning as pl
from pytorch_lightning.callbacks import EarlyStopping, ModelCheckpoint
from pytorch_lightning.loggers import WandbLogger
import wandb

# Import our custom modules
from src.skin.config import SkinConfig
from src.skin.data.datamodule import SkinDataModule
from src.skin.models.mobilenet import MediScanX_Skin_Baseline

def main():
    # 1. Initialize Configuration
    config = SkinConfig()
    pl.seed_everything(config.seed)

    # 2. Setup Data Pipeline
    print("Initializing Data Pipeline & Searching for files...")
    data_module = SkinDataModule(config)
    
    # Manually trigger data prep to extract class weights before building the model
    data_module.prepare_data()
    data_module.setup(stage='fit')
    class_weights = data_module.class_weights

    # 3. Setup Model
    print("Initializing MobileNetV3-Small Engine...")
    model = MediScanX_Skin_Baseline(config, class_weights)

    # 4. Setup MLOps Tracking (W&B) & Callbacks
    wandb_logger = WandbLogger(project=config.wandb_project, name=config.architecture)
    
    early_stop_callback = EarlyStopping(
        monitor="val_loss", patience=5, verbose=True, mode="min"
    )
    
    checkpoint_callback = ModelCheckpoint(
        dirpath="models/",
        filename="mediscanx-skin-best-{epoch:02d}-{val_loss:.3f}",
        save_top_k=1,
        verbose=True,
        monitor="val_loss",
        mode="min"
    )

    # 5. Initialize Trainer
    trainer = pl.Trainer(
        max_epochs=config.max_epochs,
        logger=wandb_logger,
        callbacks=[early_stop_callback, checkpoint_callback],
        accelerator="auto",
        devices=1,
        precision="16-mixed"
    )

    # 6. Execute Training
    print("Beginning Training Pipeline...")
    trainer.fit(model, datamodule=data_module)
    
    wandb.finish()
    print("Training Complete. Best model saved to the /models/ directory.")

if __name__ == "__main__":
    main()