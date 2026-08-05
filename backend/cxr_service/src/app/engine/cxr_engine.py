"""Asynchronous CXR inference engine – main public API."""

import asyncio
import logging
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import torch

from app.core.config import Settings as CXRInferenceConfig
from app.engine.diagnostic_engine import CXRDiagnosticEngine
from app.engine.preprocessor import CXRInferencePreprocessor
from app.core.exceptions import CXRModelNotFoundError, ModelInferenceError
from app.models.densenet121_cihmlc import DenseNet121_CIHMLC

logger = logging.getLogger(__name__)


class CXREngine:
    """Async lifecycle wrapper that loads the model, thresholds, preprocessor, and XAI engine.

    Attributes:
        cfg (CXRInferenceConfig): The configuration object for the inference engine.
        ready (bool): Flag indicating whether the engine has successfully initialized.
    """

    def __init__(self, cfg: Optional[CXRInferenceConfig] = None) -> None:
        """Initializes the CXREngine with an optional configuration.

        Args:
            cfg (Optional[CXRInferenceConfig], optional): Configuration settings for the engine. Defaults to None.
        """
        self.cfg: CXRInferenceConfig = cfg or CXRInferenceConfig()
        self._model: Optional[torch.nn.Module] = None
        self._diagnostic_engine: Optional[CXRDiagnosticEngine] = None
        self.ready: bool = False

    async def initialize(self) -> None:
        """Load model weights and build the diagnostic pipeline asynchronously off-thread."""
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._load)
        self.ready = True

    def _load(self) -> None:
        """Synchronous loading executed inside an executor thread.

        Raises:
            CXRModelNotFoundError: If the specified model weights file does not exist.
            ModelInferenceError: If the state dict cannot be loaded into the model.
            ValueError: If the thresholds file has fewer entries than the number of base labels.
        """
        weights_path: Path = Path(self.cfg.CXR_WEIGHTS_PATH)
        if not weights_path.exists():
            raise CXRModelNotFoundError(path=str(weights_path))

        model: DenseNet121_CIHMLC = DenseNet121_CIHMLC(num_classes=self.cfg.num_classes, pretrained=False)

        # weights_only=True blocks arbitrary pickle execution and silences the
        # PyTorch >= 2.0 FutureWarning.
        state_dict: Dict[str, torch.Tensor] = torch.load(weights_path, map_location="cpu", weights_only=True)
        cleaned: OrderedDict[str, torch.Tensor] = OrderedDict()
        for k, v in state_dict.items():
            k = k.replace("_orig_mod.", "").replace("module.", "").replace("model.", "")
            cleaned[k] = v

        try:
            model.load_state_dict(cleaned, strict=False)
        except Exception as exc:
            raise ModelInferenceError(
                message="Failed to load DenseNet-121 state dict.",
                context={"path": str(weights_path), "error": str(exc)},
            ) from exc

        model.eval()
        model.to(self.cfg.device)
        self._model = model

        thresholds: np.ndarray = self._load_thresholds()
        self.cfg.classification_thresholds = thresholds

        preprocessor: CXRInferencePreprocessor = CXRInferencePreprocessor(self.cfg)
        self._diagnostic_engine = CXRDiagnosticEngine(
            self.cfg, self._model, preprocessor, thresholds=thresholds
        )

    def _load_thresholds(self) -> np.ndarray:
        """Load the per-class decision thresholds for the base labels.

        Reads ``cfg.CXR_THRESHOLDS_PATH`` and keeps the first ``num_base_labels``
        values as ``float32``. Falls back to 0.5 for every base label when the
        file is missing.

        Returns:
            np.ndarray: A ``float32`` array of length ``num_base_labels``.

        Raises:
            ValueError: If the file exists but contains fewer than
                ``num_base_labels`` values.
        """
        thresholds_path: str = self.cfg.CXR_THRESHOLDS_PATH
        num_base_labels: int = len(self.cfg.chexpert_labels)

        try:
            raw_thresholds: np.ndarray = np.load(thresholds_path)
        except FileNotFoundError:
            logger.warning(
                "Thresholds file not found at %r — falling back to 0.5 for all "
                "%d base labels. Set CXR_THRESHOLDS_PATH to the correct path.",
                thresholds_path,
                num_base_labels,
            )
            return np.full(num_base_labels, 0.5, dtype=np.float32)

        if raw_thresholds.shape[0] < num_base_labels:
            raise ValueError(
                f"Thresholds file at {thresholds_path!r} contains only "
                f"{raw_thresholds.shape[0]} values; expected at least "
                f"{num_base_labels} (one per CheXpert base label). "
                f"The file may be corrupted or from an incompatible run."
            )

        # The file may hold thresholds for all 20 classes; keep the 14 base
        # labels and cast to float32 to match the sigmoid output dtype.
        thresholds: np.ndarray = raw_thresholds[:num_base_labels].astype(np.float32)
        logger.info(
            "Loaded %d calibrated per-class thresholds from %s (range: %.3f-%.3f).",
            len(thresholds),
            thresholds_path,
            float(thresholds.min()),
            float(thresholds.max()),
        )
        return thresholds

    async def predict(self, image_path: str, top_k: int = 5, use_gradcam: bool = True) -> Dict[str, Any]:
        """Run a full diagnostic pass asynchronously on a given image.

        Args:
            image_path (str): The file path to the input image for prediction.
            top_k (int, optional): The number of top predictions to return. Defaults to 5.

        Returns:
            Dict[str, Any]: A dictionary containing the original image, findings, predicted diagnoses, and patient ID.

        Raises:
            RuntimeError: If the engine has not been initialized before calling predict.
        """
        if not self.ready or self._diagnostic_engine is None:
            raise RuntimeError(
                "CXREngine is not initialised – call await engine.initialize() first"
            )
        return await self._diagnostic_engine.async_run_diagnostic(image_path, top_k, use_gradcam)
