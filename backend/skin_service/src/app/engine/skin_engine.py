"""Asynchronous Skin Lesion inference engine – main public API."""

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

import torch

from app.core.exceptions import SkinModelNotFoundError
from app.core.config import SkinInferenceConfig
from app.engine.diagnostic_engine import SkinDiagnosticEngine
from app.engine.preprocessor import SkinPreprocessor
from app.explainability.gradcam import SkinGradCAM
from app.models.efficientnet_b0 import EfficientNetB0Classifier, SkinClassifier


class SkinEngine:
    """Async lifecycle wrapper that loads the model, preprocessor, and XAI engine.

    Attributes:
        cfg (SkinInferenceConfig): The configuration object for the inference engine.
        ready (bool): Flag indicating whether the engine has successfully initialized.
    """

    def __init__(self, cfg: Optional[SkinInferenceConfig] = None) -> None:
        """Initializes the SkinEngine with an optional configuration."""
        self.cfg: SkinInferenceConfig = cfg or SkinInferenceConfig()
        self._model: Optional[torch.nn.Module] = None
        self._diagnostic_engine: Optional[SkinDiagnosticEngine] = None
        self.ready: bool = False

    async def initialize(self) -> None:
        """Load model weights and build the diagnostic pipeline asynchronously off-thread."""
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._load)
        self.ready = True

    def _load(self) -> None:
        """Synchronous loading executed inside an executor thread."""
        weights_path: Path = Path(self.cfg.model_weights_path)
        if not weights_path.exists():
            raise SkinModelNotFoundError(path=str(weights_path))

        model: torch.nn.Module = EfficientNetB0Classifier.from_weights(str(weights_path), self.cfg)

        preprocessor: SkinPreprocessor = SkinPreprocessor(self.cfg)
        xai_engine: SkinGradCAM = SkinGradCAM(
            self.cfg,
            model,
            target_layer=model.backbone.features[-1],
        )
        self._diagnostic_engine = SkinDiagnosticEngine(
            self.cfg, model, preprocessor, xai_engine
        )
        self._model = model

    async def predict(
        self, image_path: str, top_k: int = 3, use_gradcam: bool = True
    ) -> Dict[str, Any]:
        """Run a full diagnostic pass asynchronously on a given image."""
        if not self.ready or self._diagnostic_engine is None:
            raise RuntimeError(
                "SkinEngine is not initialised – call await engine.initialize() first"
            )
        return await self._diagnostic_engine.async_run_diagnostic(image_path, top_k, use_gradcam)
