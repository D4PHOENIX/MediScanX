"""Synchronous ECG diagnostic engine.

Coordinates preprocessing, ONNX / PyTorch inference and optional Grad‑CAM XAI.
"""

import asyncio
import base64
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch

from app.core.config import Settings
from .preprocessor import ECGPreprocessor
from app.core.exceptions import ECGInferenceError, ECGModelNotFoundError

logger: logging.Logger = logging.getLogger(__name__)


class ECGDiagnosticEngine:
    """Orchestration engine for ECG preprocessing, inference and Grad-CAM visualisation.

    Attributes:
        cfg (Settings): The configuration settings.
        onnx_session (Any): Active ONNX inference session.
        model (Optional[torch.nn.Module]): The underlying PyTorch model.
        preprocessor (ECGPreprocessor): The preprocessor for input signals.
        xai_engine (Optional[Any]): The Grad-CAM explainability engine.
    """

    def __init__(
        self,
        cfg: Settings,
        onnx_session: Any,
        model: Optional[torch.nn.Module],
        preprocessor: ECGPreprocessor,
        xai_engine: Optional[Any],
    ) -> None:
        """Initialise the diagnostic engine.

        Args:
            cfg (Settings): Configuration mapping.
            onnx_session (Any): Active ONNX inference session.
            model (Optional[torch.nn.Module]): Fallback PyTorch model.
            preprocessor (ECGPreprocessor): Instantiated preprocessor pipeline.
            xai_engine (Optional[Any]): Instantiated XAI engine if available.
        """
        self.cfg: Settings = cfg
        self.onnx_session: Any = onnx_session
        self.model: Optional[torch.nn.Module] = model
        self.preprocessor: ECGPreprocessor = preprocessor
        self.xai_engine: Optional[Any] = xai_engine

    # ------------------------------------------------------------------
    #  Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _encode_image(img: np.ndarray) -> str:
        """Convert a numpy RGB uint8 image to a base64‑encoded PNG string.

        Args:
            img (np.ndarray): Image array of shape (H, W, 3).

        Returns:
            str: Base64-encoded PNG image string.
        """
        import cv2
        _: Any
        buf: np.ndarray
        _, buf = cv2.imencode('.png', cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
        return base64.b64encode(buf).decode('utf-8')

    # ------------------------------------------------------------------
    #  Diagnostic pipeline
    # ------------------------------------------------------------------
    def run_diagnostic(
        self,
        input_path: str,
        input_type: str = 'wfdb',
        use_gradcam: bool = False,
        top_k: int = 5,
        diagnostic_mode: bool = False,
        diagnostic_out_dir: str = "/app/data/ecg_diagnostics",
    ) -> Dict[str, Any]:
        """Execute a synchronous diagnostic pass.

        Args:
            input_path (str): Path to the WFDB record or the scanned ECG image.
            input_type (str): ``'wfdb'`` or ``'image'``. Defaults to 'wfdb'.
            use_gradcam (bool): If ``True``, use the PyTorch backend and generate
                Grad‑CAM overlays. Defaults to False.
            top_k (int): Number of findings to return. Defaults to 5.

        Returns:
            Dict[str, Any]: Dictionary conforming to the diagnostic‑result schema.

        Raises:
            ValueError: If input_type is unsupported.
            ECGInferenceError: If inference or XAI fails.
            ECGModelNotFoundError: If PyTorch model is missing but Grad-CAM is requested.
        """
        t_start: float = time.perf_counter()

        # ---- 1. Preprocessing -------------------------------------------------
        tensor: torch.Tensor
        signal_array: np.ndarray
        if input_type == 'wfdb':
            tensor, signal_array = self.preprocessor.process_wfdb(input_path)
        elif input_type == 'image':
            tensor, signal_array = self.preprocessor.process_image(
                input_path, 
                diagnostic_mode=diagnostic_mode, 
                diagnostic_out_dir=diagnostic_out_dir
            )
        else:
            raise ValueError(f"Unsupported input_type: {input_type!r}")

        tensor = tensor.to(self.cfg.device)
        
        # Ensure tensor is completely finite before invoking the model
        if not torch.isfinite(tensor).all():
            raise ECGInferenceError("Preprocessed tensor contains non-finite values (NaN/Inf).")
        
        # Use lead I for visualisation overlays (index 0)
        try:
            one_lead_signal: np.ndarray = signal_array[0]
            one_lead_signal = np.nan_to_num(one_lead_signal, nan=0.0, posinf=0.0, neginf=0.0)
        except IndexError as e:
            raise ECGInferenceError("Signal array is empty or lacks required leads.") from e

        # ---- 2. Inference ----------------------------------------------------
        full_probs: np.ndarray
        if use_gradcam or self.onnx_session is None:
            # PyTorch path — required for Grad-CAM backward pass.
            if self.model is None:
                raise ECGModelNotFoundError(
                    "PyTorch model required (ONNX is unavailable)"
                )
            try:
                with torch.no_grad():
                    if not torch.isfinite(tensor).all():
                        raise ECGInferenceError("Preprocessed tensor contains non-finite values (NaN/Inf).")
                    logits: torch.Tensor = self.model(tensor)
                full_probs = torch.sigmoid(logits).squeeze().detach().cpu().numpy()
            except RuntimeError as e:
                if "out of memory" in str(e).lower():
                    raise ECGInferenceError("GPU memory exhaustion during PyTorch inference.") from e
                raise ECGInferenceError(f"PyTorch inference failed: {e}") from e

        else:
            # ONNX path — no gradients needed.
            try:
                with torch.no_grad():
                    # Ensure tensor is completely finite before invoking the model
                    if not torch.isfinite(tensor).all():
                        raise ECGInferenceError("Preprocessed tensor contains non-finite values (NaN/Inf).")
                    input_np: np.ndarray = tensor.cpu().numpy().astype(np.float32)
                ort_inputs: Dict[str, np.ndarray] = {
                    self.onnx_session.get_inputs()[0].name: input_np
                }
                ort_outputs: List[Any] = self.onnx_session.run(None, ort_inputs)
                full_probs = torch.sigmoid(
                    torch.tensor(ort_outputs[0])
                ).squeeze().cpu().numpy()
            except Exception as e:
                raise ECGInferenceError(f"ONNX inference failed: {e}") from e

        num_labels: int = len(self.cfg.ecg_labels)
        base_probs: np.ndarray = full_probs[:num_labels]
        top_indices: np.ndarray = np.argsort(base_probs)[::-1][:top_k]

        # ---- 3. Build findings -----------------------------------------------
        top_findings: List[Dict[str, Any]] = []
        class_idx: np.intp
        for class_idx in top_indices:
            score: float = float(base_probs[class_idx])
            label: str = self.cfg.ecg_labels[class_idx]

            overlay_b64: Optional[str] = None
            if use_gradcam and self.xai_engine is not None:
                try:
                    with self.xai_engine as gradcam:
                        heatmap: np.ndarray = gradcam.generate_heatmap(tensor, int(class_idx))
                        overlay_img: np.ndarray = gradcam.render_overlay(
                            one_lead_signal, heatmap, lead_name="I"
                        )
                    overlay_b64 = self._encode_image(overlay_img)
                except RuntimeError as e:
                    if "out of memory" in str(e).lower():
                        raise ECGInferenceError("GPU memory exhaustion during Grad-CAM generation.") from e
                    raise ECGInferenceError(f"Grad-CAM generation failed: {e}") from e

            top_findings.append({
                "label": label,
                "class_idx": int(class_idx),
                "confidence": score,
                "overlay_img": overlay_b64,
            })

        t_end: float = time.perf_counter()
        inference_time_ms: float = (t_end - t_start) * 1000.0

        return {
            "predictions": top_findings,
            "predicted_class": (
                top_findings[0]["label"] if top_findings else None
            ),
            "predicted_confidence": (
                top_findings[0]["confidence"] if top_findings else None
            ),
            "gradcam_overlay": (
                top_findings[0]["overlay_img"] if top_findings else None
            ),
            "inference_time_ms": inference_time_ms,
            "patient_id": Path(input_path).name,
        }

    async def async_run_diagnostic(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """Run the diagnostic asynchronously (thread‑offloaded).

        PyTorch inference (CPU or GPU) and Grad-CAM backward passes are
        CPU-bound and must not block the uvicorn event loop. Delegating
        to ``asyncio.to_thread`` moves the entire synchronous pipeline to
        the default ThreadPoolExecutor.

        Args:
            *args (Any): Positional arguments passed to run_diagnostic.
            **kwargs (Any): Keyword arguments passed to run_diagnostic.

        Returns:
            Dict[str, Any]: Dictionary conforming to the diagnostic‑result schema.
        """
        return await asyncio.to_thread(
            self.run_diagnostic, *args, **kwargs
        )
