"""Synchronous diagnostic engine that coordinates preprocessing, inference and XAI."""

import asyncio
import base64
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List

import cv2
import numpy as np
import torch

from app.core.config import Settings as CXRInferenceConfig
from app.engine.preprocessor import CXRInferencePreprocessor
from app.core.exceptions import InvalidTensorShapeError, ModelInferenceError
from app.explainability.gradcam import GradCAMPlusPlus


class CXRDiagnosticEngine:
    """Orchestration engine for CXR inference and Grad-CAM++ visualisation.

    Runs preprocessing, the dual-output DenseNet-121 forward pass, per-class
    thresholding, and Grad-CAM++ overlay generation, returning a JSON-ready
    payload.

    Attributes:
        cfg (CXRInferenceConfig): Configuration settings for inference.
        model (torch.nn.Module): The PyTorch neural network model.
        preprocessor (CXRInferencePreprocessor): Image preprocessor.
        xai_engine (GradCAMPlusPlus): Grad-CAM++ visualization engine.
        thresholds (Optional[np.ndarray]): Per-class decision thresholds.
    """

    def __init__(
        self,
        cfg: CXRInferenceConfig,
        model: torch.nn.Module,
        preprocessor: CXRInferencePreprocessor,
        xai_engine: GradCAMPlusPlus,
        thresholds: Optional[np.ndarray] = None,
    ) -> None:
        """Initializes the CXRDiagnosticEngine.

        Args:
            cfg (CXRInferenceConfig): The configuration settings.
            model (torch.nn.Module): The underlying PyTorch model.
            preprocessor (CXRInferencePreprocessor): The preprocessor for input images.
            xai_engine (GradCAMPlusPlus): The Grad-CAM++ explainability engine.
            thresholds (Optional[np.ndarray], optional): Per-class thresholds. Defaults to None.
        """
        self.cfg: CXRInferenceConfig = cfg
        self.model: torch.nn.Module = model
        self.preprocessor: CXRInferencePreprocessor = preprocessor
        self.xai_engine: GradCAMPlusPlus = xai_engine
        self.thresholds: Optional[np.ndarray] = thresholds

    @staticmethod
    def _encode_image(img: np.ndarray) -> str:
        """Convert a numpy image (RGB uint8) to a base64‑encoded PNG string.

        Args:
            img (np.ndarray): The input image array in RGB format.

        Returns:
            str: The base64-encoded PNG string representation of the image.
        """
        _: bool
        buffer: np.ndarray
        _, buffer = cv2.imencode(".png", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
        return base64.b64encode(buffer).decode("utf-8")

    def run_diagnostic(self, image_path: str, top_k: int = 5, use_gradcam: bool = True) -> Dict[str, Any]:
        """Execute a complete diagnostic pass on a chest X-ray image (synchronous).

        Args:
            image_path (str): The file path to the input image.
            top_k (int, optional): The number of top predictions to generate. Defaults to 5.

        Returns:
            Dict[str, Any]: A dictionary containing the original image, findings, predicted diagnoses, and patient ID.

        Raises:
            InvalidTensorShapeError: If the preprocessed tensor does not match the expected shape.
            ModelInferenceError: If the underlying model forward pass fails.
        """
        # Preprocessing
        input_tensor: torch.Tensor
        visual_base_rgb: np.ndarray
        input_tensor, visual_base_rgb = self.preprocessor.process(image_path)
        try:
            input_tensor = input_tensor.to(self.cfg.device)
        except RuntimeError as exc:
            raise ModelInferenceError(
                message="Memory error or failed to move tensor to device.",
                context={"error": str(exc)},
            ) from exc

        expected_shape: Tuple[int, int, int, int] = (1, 3, self.cfg.image_size[0], self.cfg.image_size[1])
        if tuple(input_tensor.shape) != expected_shape:
            raise InvalidTensorShapeError(
                message="Preprocessed tensor has an unexpected shape.",
                context={
                    "expected": list(expected_shape),
                    "actual": list(input_tensor.shape),
                },
            )

        # Forward pass for probabilities (Grad-CAM++ needs grad)
        try:
            # Run the model once WITH grad tracking: spatial_features must stay
            # attached to the graph so Grad-CAM++ can backprop through it, while
            # probabilities are read from detached logits outside the graph.
            logits: torch.Tensor
            spatial_features: torch.Tensor
            if use_gradcam:
                logits, spatial_features = self.model(input_tensor)
                full_probs: np.ndarray = torch.sigmoid(logits.detach()).squeeze().cpu().numpy()
            else:
                with torch.no_grad():
                    logits, spatial_features = self.model(input_tensor)
                    full_probs: np.ndarray = torch.sigmoid(logits).squeeze().cpu().numpy()
        except Exception as exc:
            raise ModelInferenceError(
                message="DenseNet-121 forward pass failed.",
                context={"error": str(exc)},
            ) from exc

        num_base_labels: int = len(self.cfg.chexpert_labels)
        base_probs: np.ndarray = full_probs[:num_base_labels]

        top_indices: np.ndarray = np.argsort(base_probs)[::-1][:top_k]

        # Build findings (with Grad‑CAM++ overlays) 
        top_findings: List[Dict[str, Any]] = []
        try:
            class_idx: int
            for class_idx in top_indices:
                score: float = float(base_probs[class_idx])
                label: str = self.cfg.chexpert_labels[class_idx]

                finding = {
                    "label": label,
                    "class_idx": int(class_idx),
                    "confidence": round(score, 4),
                }

                if use_gradcam:
                    heatmap: np.ndarray = self.xai_engine.generate_heatmap(logits, spatial_features, int(class_idx))
                    overlay: np.ndarray = self.xai_engine.blend_overlay(visual_base_rgb, heatmap)
                    overlay_b64: str = self._encode_image(overlay)
                    finding["overlay_img"] = overlay_b64

                top_findings.append(finding)
        except RuntimeError as exc:
            raise ModelInferenceError(
                message="Grad-CAM++ heatmap generation failed.",
                context={"error": str(exc)},
            ) from exc

        thresholds: np.ndarray = (
            self.thresholds
            if self.thresholds is not None
            else np.full(num_base_labels, 0.5, dtype=np.float32)
        )
        predicted_mask: np.ndarray = base_probs > thresholds
        predicted_labels: List[str] = [
            self.cfg.chexpert_labels[i]
            for i in range(num_base_labels)
            if predicted_mask[i]
        ]

        return {
            "original_img": self._encode_image(visual_base_rgb),
            "top_findings": top_findings,
            "patient_id": Path(image_path).name,
            "predicted_diagnoses": predicted_labels,
        }

    async def async_run_diagnostic(self, image_path: str, top_k: int = 5, use_gradcam: bool = True) -> Dict[str, Any]:
        """Execute the diagnostic pass asynchronously by offloading CPU work to a thread.

        PyTorch inference and Grad-CAM++ backward passes are CPU-bound operations
        that must not block the uvicorn event loop.

        Args:
            image_path (str): The file path to the input image.
            top_k (int, optional): The number of top predictions to generate. Defaults to 5.

        Returns:
            Dict[str, Any]: A dictionary containing the original image, findings, predicted diagnoses, and patient ID.
        """
        return await asyncio.to_thread(self.run_diagnostic, image_path, top_k, use_gradcam)
