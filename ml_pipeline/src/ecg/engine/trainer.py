"""
Execution engine for ECG model orchestration.
Manages training, validation, checkpointing, and evaluation dashboard rendering.
"""

from __future__ import annotations

from typing import Any

import pytorch_lightning as pl
import torch
from pytorch_lightning.callbacks import EarlyStopping, ModelCheckpoint

from src.core.telemetry import ExperimentTracker
from src.ecg.config import ECGTrainingConfig
from src.ecg.data.datamodule import ECGDataModule
from src.ecg.models.cnn_bilstm import MediScanXECGClassifier
from src.ecg.utils.metrics import ECGEvaluationDashboard


class ECGTrainingPipeline:
    """End-to-end orchestration layer for ECG model training and evaluation."""

    def __init__(self, cfg: ECGTrainingConfig) -> None:
        self.cfg = cfg

    def _build_callbacks(self) -> list[Any]:
        """Create the checkpointing and early-stopping callbacks."""

        checkpoint_callback = ModelCheckpoint(
            monitor="val_loss",
            dirpath=self.cfg.checkpoint_dir,
            filename="mediscanx-best-ecg-model-{epoch:02d}-{val_loss:.3f}",
            save_top_k=1,
            mode="min",
        )
        early_stop_callback = EarlyStopping(
            monitor="val_loss",
            min_delta=0.0,
            patience=5,
            verbose=True,
            mode="min",
        )
        return [checkpoint_callback, early_stop_callback]

    def run(self) -> None:
        """Execute the ECG training workflow."""

        torch.set_float32_matmul_precision("medium")
        pl.seed_everything(self.cfg.seed)

        ExperimentTracker.initialize(self.cfg)
        data_module = ECGDataModule(self.cfg)
        train_loader, val_loader = data_module.setup()

        model = MediScanXECGClassifier(self.cfg)
        callbacks = self._build_callbacks()

        trainer = pl.Trainer(
            max_epochs=self.cfg.max_epochs,
            accelerator="gpu" if self.cfg.device.type == "cuda" else "cpu",
            devices=1,
            log_every_n_steps=10,
            callbacks=callbacks,
        )

        print("Starting ECG training pipeline...")
        trainer.fit(model, train_loader, val_loader)

        checkpoint_callback = callbacks[0]
        if isinstance(checkpoint_callback, ModelCheckpoint):
            print(f"Training stopped. Best model saved at: {checkpoint_callback.best_model_path}")
            best_model = MediScanXECGClassifier.load_from_checkpoint(
                checkpoint_callback.best_model_path,
                cfg=self.cfg,
            )
            ECGEvaluationDashboard.plot(
                model=best_model,
                dataloader=val_loader,
                class_names=data_module.class_names,
                device=self.cfg.device,
            )

        ExperimentTracker.close()
