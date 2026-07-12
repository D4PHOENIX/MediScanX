"""Asynchronous ECG inference engine – main public API."""

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

import torch

from app.models.cnn_bilstm import ECGClassifier
from app.core.exceptions import ECGInferenceError

from app.core.config import Settings
from .preprocessor import ECGPreprocessor
from .diagnostic_engine import ECGDiagnosticEngine


class ECGEngine:
    """Async lifecycle wrapper that loads the model, preprocessor, and XAI engine.

    Attributes:
        cfg (Settings): The configuration object for the inference engine.
        ready (bool): Flag indicating whether the engine has successfully initialized.
    """

    def __init__(self, cfg: Optional[Settings] = None) -> None:
        """Initialise the ECGEngine with the given or default configuration.

        Args:
            cfg (Optional[Settings]): Configuration for ECG inference.
                If None, the default configuration is used.
        """
        self.cfg: Settings = cfg or Settings()
        self._model: Optional[torch.nn.Module] = None
        self._onnx_session: Optional[Any] = None
        self._preprocessor: Optional[ECGPreprocessor] = None
        self._diagnostic_engine: Optional[ECGDiagnosticEngine] = None
        self._xai_engine: Optional[Any] = None
        self.ready: bool = False

    async def initialize(self) -> None:
        """Load model weights and build the diagnostic pipeline asynchronously.

        Heavy I/O (``torch.load``, ONNX session creation) is off‑loaded
        to a thread so the event loop stays responsive during startup.
        """
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._load)
        self.ready = True

    def _load(self) -> None:
        """Synchronous loading procedure.

        Called from an executor thread to load the ONNX session, PyTorch model,
        preprocessor, explainability engine, and diagnostic engine without blocking.

        Raises:
            ECGInferenceError: If GPU memory exhaustion occurs during PyTorch model loading.
        """
        _ort_available: bool
        try:
            import onnxruntime as ort  
            _ort_available = True
        except ImportError:
            _ort_available = False

        # 1. ONNX session 
        onnx_path: Path = Path(self.cfg.onnx_model_path)
        if _ort_available and onnx_path.exists():
            try:
                self._onnx_session = ort.InferenceSession(str(onnx_path))
            except Exception as e:
                print(f"Warning: Failed to load ONNX model: {e}")
                self._onnx_session = None
        else:
            self._onnx_session = None

        # 2. PyTorch model (fallback & Grad-CAM) 
        ckpt_path: Path = Path(self.cfg.pytorch_ckpt_path)
        if ckpt_path.exists():
            try:
                self._model = ECGClassifier.from_checkpoint(
                    str(ckpt_path),
                    device=self.cfg.device,
                    num_leads=self.cfg.num_leads,
                    num_classes=self.cfg.num_classes,
                )
            except RuntimeError as e:
                if "out of memory" in str(e).lower():
                    raise ECGInferenceError("GPU memory exhaustion during PyTorch model loading.") from e
                raise
        else:
            self._model = None

        # Preprocessor 
        self._preprocessor = ECGPreprocessor(self.cfg)

        # XAI engine (only when a PyTorch model is available) 
        if self._model is not None:
            from app.explainability.gradcam_1d import GradCAM1D
            self._xai_engine = GradCAM1D(self.cfg, self._model)
        else:
            self._xai_engine = None

        # Diagnostic engine 
        self._diagnostic_engine = ECGDiagnosticEngine(
            self.cfg,
            self._onnx_session,
            self._model,
            self._preprocessor,
            self._xai_engine,
        )

    async def predict(
        self,
        image_path: str,
        top_k: int = 5,
        input_type: str = 'wfdb',
        use_gradcam: bool = False,
    ) -> Dict[str, Any]:
        """Run a full diagnostic pass asynchronously.

        Args:
            image_path (str): Path to the input file (WFDB record or scanned image).
            top_k (int): Number of findings to return. Defaults to 5.
            input_type (str): ``'wfdb'`` or ``'image'``. Defaults to ``'wfdb'``.
            use_gradcam (bool): If ``True``, the PyTorch backend is used instead of
                ONNX and Grad‑CAM overlays are generated. Defaults to False.

        Returns:
            Dict[str, Any]: A JSON‑serialisable dict containing predictions and metadata.

        Raises:
            RuntimeError: If the ECGEngine is not fully initialised.
        """
        if not self.ready or self._diagnostic_engine is None:
            raise RuntimeError(
                "ECGEngine is not initialised – "
                "call await engine.initialize() first"
            )
        result: Dict[str, Any] = await self._diagnostic_engine.async_run_diagnostic(
            image_path,
            input_type=input_type,
            use_gradcam=use_gradcam,
            top_k=top_k,
        )
        return result
