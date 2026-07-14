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
from app.models.mobilenet_v3 import SkinClassifier


class SkinEngine:
    """Async lifecycle wrapper that loads the model, preprocessor, and XAI engine.

    Attributes:
        cfg (SkinInferenceConfig): The configuration object for the inference engine.
        ready (bool): Flag indicating whether the engine has successfully initialized.
    """

    def __init__(self, cfg: Optional[SkinInferenceConfig] = None) -> None:
        """Initializes the SkinEngine with an optional configuration.

        Args:
            cfg (Optional[SkinInferenceConfig], optional): Configuration settings for the engine. Defaults to None.
        """
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
        """Synchronous loading executed inside an executor thread.

        Raises:
            SkinModelNotFoundError: If the specified model weights file does not exist.
        """
        weights_path: Path = Path(self.cfg.model_weights_path)
        if not weights_path.exists():
            raise SkinModelNotFoundError(path=str(weights_path))

        model: torch.nn.Module = SkinClassifier.from_weights(str(weights_path), self.cfg)

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
        self, image_path: str, top_k: int = 3
    ) -> Dict[str, Any]:
        """Run a full diagnostic pass asynchronously on a given image.

        Args:
            image_path (str): The file path to the input image for prediction.
            top_k (int, optional): The number of top predictions to return. Defaults to 3.

        Returns:
            Dict[str, Any]: A dictionary containing the original image, findings, predicted class, and patient ID.

        Raises:
            RuntimeError: If the engine has not been initialized before calling predict.
        """
        if not self.ready or self._diagnostic_engine is None:
            raise RuntimeError(
                "SkinEngine is not initialised – call await engine.initialize() first"
            )
        return await self._diagnostic_engine.async_run_diagnostic(image_path, top_k)
