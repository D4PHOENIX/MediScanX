"""
MediScanX: ECG model training entry point.
Binds configuration, data routing, model architecture, and trainer execution.
"""

from __future__ import annotations

from src.ecg.config import ECGTrainingConfig
from src.ecg.engine.trainer import ECGTrainingPipeline


def main() -> None:
    """Execute the end-to-end ECG training pipeline."""

    cfg = ECGTrainingConfig()
    print(f"Executing MediScanX ECG training on: {cfg.device}")
    pipeline = ECGTrainingPipeline(cfg)
    pipeline.run()


if __name__ == "__main__":
    main()
