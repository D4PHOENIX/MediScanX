"""
Standalone execution script for end-to-end ECG inference and Grad-CAM visualization.
Supports both refactored and legacy checkpoint architectures.
"""

from __future__ import annotations

import torch
from torch import nn

from src.ecg.config import ECGInferenceConfig, ECGTrainingConfig
from MediScanX.ml_pipeline.src.ecg.data.preprocessor import ECGPreprocessor
from MediScanX.ml_pipeline.src.ecg.engine.diagnostic_engine import ECGInferenceEngine
from MediScanX.ml_pipeline.src.ecg.models.cnn_bilstm import MediScanXECGClassifier
from MediScanX.ml_pipeline.src.ecg.models.legacy_resnet_bilstm import LegacyGradCAMECGClassifier
from MediScanX.ml_pipeline.src.ecg.utils.explainability import GradCAM1D


def load_model(cfg: ECGInferenceConfig) -> tuple[nn.Module, nn.Module]:
    """Load the correct ECG model architecture based on checkpoint keys."""

    checkpoint = torch.load(cfg.checkpoint_path, map_location=cfg.device)
    state_dict = checkpoint["state_dict"] if "state_dict" in checkpoint else checkpoint

    if any(key.startswith("initial_conv") or key.startswith("res_block") for key in state_dict.keys()):
        model = LegacyGradCAMECGClassifier(cfg)
        target_layer = model.res_block2
        model_name = "legacy residual ECG architecture"
    else:
        training_cfg = ECGTrainingConfig(
            data_dir=cfg.data_dir,
            num_leads=cfg.num_leads,
            seq_length=cfg.seq_length,
            full_signal_length=cfg.full_signal_length,
            target_classes=cfg.target_classes,
            device=cfg.device,
        )
        model = MediScanXECGClassifier(training_cfg)
        target_layer = model.conv3
        model_name = "refactored CNN-BiLSTM ECG architecture"

    model.load_state_dict(state_dict, strict=True)
    model.to(cfg.device)
    model.eval()
    print(f"MediScanX ECG model loaded successfully using the {model_name}.")
    return model, target_layer


def main() -> None:
    """Execute one end-to-end ECG inference and Grad-CAM run."""

    cfg = ECGInferenceConfig()
    print(f"Executing MediScanX ECG inference on: {cfg.device}")
    model, target_layer = load_model(cfg)
    preprocessor = ECGPreprocessor(cfg)
    gradcam = GradCAM1D(cfg, model, target_layer)
    engine = ECGInferenceEngine(cfg, model, preprocessor, gradcam)

    results = engine.run(cfg.sample_file_path, target_class_idx=1, lead_idx=1)
    engine.visualize(results)


if __name__ == "__main__":
    main()
