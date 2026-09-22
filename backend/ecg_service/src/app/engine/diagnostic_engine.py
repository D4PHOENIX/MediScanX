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
from app.core.exceptions import ECGInferenceError, ECGModelNotFoundError
from .preprocessor import ECGPreprocessor

# ── Clinical lead relevance map (Option B Grad-CAM) ────────────────────────
# Maps each diagnostic superclass to the single ECG lead that best expresses
# its pathological features, following standard clinical ECG interpretation.
#
# NORM  → Lead I    : Reference lead for normal sinus rhythm & axis.
# MI    → V1        : Anteroseptal infarction — ST elevation, Q waves, R-loss.
# STTC  → V4        : ST-T changes most prominent in mid-precordial leads.
# CD    → V1        : Bundle branch blocks & conduction defects clearest in V1.
# HYP   → aVL       : LV hypertrophy voltage criteria (Sokolow-Lyon / Cornell).
_LABEL_TO_LEAD: Dict[str, str] = {
    "NORM": "I",
    "MI":   "V1",
    "STTC": "V4",
    "CD":   "V1",
    "HYP":  "aVL",
}

# Standard 3×4 ECG lead order — matches preprocessor signal_array row indices.
_LEAD_ORDER: List[str] = [
    "I",   "aVR", "V1", "V4",
    "II",  "aVL", "V2", "V5",
    "III", "aVF", "V3", "V6",
]

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
    ) -> Dict[str, Any]:
        """Execute a synchronous diagnostic pass.

        Args:
            input_path (str): Path to the WFDB record or the scanned ECG image.
            input_type (str): ``'wfdb'`` or ``'image'``. Defaults to 'wfdb'.
            use_gradcam (bool): If ``True``, use the PyTorch backend and generate
                Grad‑CAM overlays. Defaults to False.
            top_k (int): Number of findings to return. Defaults to 5.
            diagnostic_mode (bool): If ``True``, write debug images and signals to
                ``cfg.ecg_diagnostic_dir`` (default ``/app/data/ecg_diagnostics``).
                Directory is configured via ``Settings.ecg_diagnostic_dir``; there
                is no per-call path override (removed in commit 712abc8).

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
        rhythm_tensor: Optional[torch.Tensor] = None
        volt_tensor: Optional[torch.Tensor] = None
        signal_array: np.ndarray

        if input_type == 'wfdb':
            if isinstance(self.preprocessor, ECGPreprocessor):
                res = self.preprocessor.process_wfdb_dualbranch(input_path)
            elif hasattr(self.preprocessor, "process_wfdb"):
                res = self.preprocessor.process_wfdb(input_path)
            else:
                res = self.preprocessor.process_wfdb_dualbranch(input_path)

        elif input_type == 'image':
            if isinstance(self.preprocessor, ECGPreprocessor):
                res = self.preprocessor.process_image_dualbranch(
                    input_path,
                    diagnostic_mode=diagnostic_mode,
                )
            elif hasattr(self.preprocessor, "process_image"):
                res = self.preprocessor.process_image(
                    input_path,
                    diagnostic_mode=diagnostic_mode,
                )
            else:
                res = self.preprocessor.process_image_dualbranch(
                    input_path,
                    diagnostic_mode=diagnostic_mode,
                )
        else:
            raise ValueError(f"Unsupported input_type: {input_type!r}")

        if isinstance(res, tuple) and len(res) == 4:
            tensor, rhythm_tensor, volt_tensor, signal_array = res
        elif isinstance(res, tuple) and len(res) == 2:
            tensor, signal_array = res
        else:
            tensor, signal_array = res[0], res[1]

        tensor = tensor.to(self.cfg.device)
        if rhythm_tensor is not None:
            rhythm_tensor = rhythm_tensor.to(self.cfg.device)
        if volt_tensor is not None:
            volt_tensor = volt_tensor.to(self.cfg.device)

        # Ensure tensors are completely finite before invoking the model
        if not torch.isfinite(tensor).all():
            raise ECGInferenceError("Preprocessed tensor contains non-finite values (NaN/Inf).")
        if rhythm_tensor is not None and not torch.isfinite(rhythm_tensor).all():
            raise ECGInferenceError("Preprocessed rhythm tensor contains non-finite values (NaN/Inf).")
        if volt_tensor is not None and not torch.isfinite(volt_tensor).all():
            raise ECGInferenceError("Preprocessed volt tensor contains non-finite values (NaN/Inf).")

        # Validate signal array shape before entering the findings loop.
        # The per-finding Grad-CAM overlay lead is selected inside the loop
        # using _LABEL_TO_LEAD, so we only need a shape guard here.
        if signal_array.ndim != 2 or signal_array.shape[0] != self.cfg.num_leads:
            raise ECGInferenceError(
                f"Signal array has unexpected shape {signal_array.shape}; "
                f"expected ({self.cfg.num_leads}, {self.cfg.seq_length})."
            )

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
                    if rhythm_tensor is not None and volt_tensor is not None:
                        logits: torch.Tensor = self.model(tensor, rhythm_tensor, volt_tensor)
                    else:
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

        # Per-class calibrated thresholds (Notebook 04b, Fold 9)
        thresholds: List[float] = list(self.cfg.ecg_thresholds)

        # ---- 3. Build findings -----------------------------------------------
        top_findings: List[Dict[str, Any]] = []
        class_idx: np.intp
        for class_idx in top_indices:
            score: float = float(base_probs[class_idx])
            label: str = self.cfg.ecg_labels[class_idx]
            threshold: float = (
                thresholds[int(class_idx)]
                if int(class_idx) < len(thresholds)
                else self.cfg.classification_threshold
            )

            overlay_b64: Optional[str] = None
            overlay_lead_name: Optional[str] = None
            if use_gradcam and self.xai_engine is not None:
                # Select the single most clinically relevant lead for this class.
                # Falls back to Lead I if the label is not in the relevance map
                # (e.g. future labels added without updating the map).
                overlay_lead_name = _LABEL_TO_LEAD.get(label, "I")
                try:
                    lead_row_idx: int = _LEAD_ORDER.index(overlay_lead_name)
                except ValueError:
                    # Defensive fallback: lead name not in canonical order.
                    lead_row_idx = 0
                    overlay_lead_name = _LEAD_ORDER[0]

                try:
                    selected_signal: np.ndarray = np.nan_to_num(
                        signal_array[lead_row_idx],
                        nan=0.0, posinf=0.0, neginf=0.0,
                    )
                    with self.xai_engine as gradcam:
                        heatmap: np.ndarray = gradcam.generate_heatmap(tensor, int(class_idx))
                        overlay_img: np.ndarray = gradcam.render_overlay(
                            selected_signal,
                            heatmap,
                            lead_name=overlay_lead_name,
                            condition_label=label,
                            confidence=score,
                        )
                    overlay_b64 = self._encode_image(overlay_img)
                    logger.debug(
                        "Grad-CAM overlay rendered for class '%s' on lead '%s'.",
                        label, overlay_lead_name,
                    )
                except RuntimeError as e:
                    if "out of memory" in str(e).lower():
                        raise ECGInferenceError("GPU memory exhaustion during Grad-CAM generation.") from e
                    raise ECGInferenceError(f"Grad-CAM generation failed: {e}") from e

            top_findings.append({
                "label": label,
                "class_idx": int(class_idx),
                "confidence": score,
                "above_threshold": score >= threshold,
                "threshold": threshold,
                "overlay_img": overlay_b64,
                "overlay_lead": overlay_lead_name,
            })

        t_end: float = time.perf_counter()
        inference_time_ms: float = (t_end - t_start) * 1000.0

        return {
            "predictions": top_findings,
            "predicted_class": (
                top_findings[0]["label"] if top_findings else None
            ),
            "confidence": (
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
