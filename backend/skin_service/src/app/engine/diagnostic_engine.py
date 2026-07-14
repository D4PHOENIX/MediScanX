"""Synchronous diagnostic engine that coordinates preprocessing, inference and XAI."""

import asyncio
import base64
from pathlib import Path
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np
import torch
import torch.nn.functional as F

from app.core.config import SkinInferenceConfig
from app.explainability.gradcam import SkinGradCAM
from app.engine.preprocessor import SkinPreprocessor


class SkinDiagnosticEngine:
    """Orchestration engine for skin‑lesion inference and Grad‑CAM visualisation.

    Attributes:
        cfg (SkinInferenceConfig): Configuration settings for inference.
        model (torch.nn.Module): The PyTorch neural network model.
        preprocessor (SkinPreprocessor): Image preprocessor.
        xai_engine (SkinGradCAM): Grad-CAM visualization engine.
    """

    def __init__(
        self,
        cfg: SkinInferenceConfig,
        model: torch.nn.Module,
        preprocessor: SkinPreprocessor,
        xai_engine: SkinGradCAM,
    ) -> None:
        """Initializes the SkinDiagnosticEngine.

        Args:
            cfg (SkinInferenceConfig): The configuration settings.
            model (torch.nn.Module): The underlying PyTorch model.
            preprocessor (SkinPreprocessor): The preprocessor for input images.
            xai_engine (SkinGradCAM): The Grad-CAM explainability engine.
        """
        self.cfg: SkinInferenceConfig = cfg
        self.model: torch.nn.Module = model
        self.preprocessor: SkinPreprocessor = preprocessor
        self.xai_engine: SkinGradCAM = xai_engine

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
        _, buffer = cv2.imencode('.png', cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
        return base64.b64encode(buffer).decode('utf-8')

    def run_diagnostic(self, image_path: str, top_k: int = 3) -> Dict[str, Any]:
        """Execute a complete diagnostic pass on a skin lesion image (synchronous).

        Args:
            image_path (str): The file path to the input image.
            top_k (int, optional): The number of top predictions to generate. Defaults to 3.

        Returns:
            Dict[str, Any]: A dictionary containing the original image, findings, predicted class, and patient ID.
        
        Raises:
            ModelInferenceError: If the underlying model forward pass fails.
        """
        # 1. Preprocessing 
        input_tensor: torch.Tensor
        visual_base_rgb: np.ndarray
        input_tensor, visual_base_rgb = self.preprocessor.process(image_path)
        input_tensor = input_tensor.to(self.cfg.device)

        # 2. Forward pass for probabilities (no grad needed here) 
        # Ensure the outer tensor is grad-free before computing probabilities.
        with torch.no_grad():
            try:
                logits: torch.Tensor = self.model(input_tensor)          # (1, num_classes)
            except Exception as e:
                from app.core.exceptions import ModelInferenceError
                raise ModelInferenceError("PyTorch forward pass failed") from e

        probs: torch.Tensor = F.softmax(logits, dim=1)               # (1, num_classes)
        probs_np: np.ndarray = probs.squeeze().cpu().numpy()        # (num_classes,)

        top_indices: np.ndarray = np.argsort(probs_np)[::-1][:top_k]   # descending

        # 3. Build findings (with Grad‑CAM overlays) 
        # Use SkinGradCAM as a context manager to ensure hooks are cleanly registered and removed.
        top_findings: List[Dict[str, Any]] = []
        with self.xai_engine as gradcam:
            for class_idx in top_indices:
                label: str = self.cfg.skin_labels[class_idx]
                abbrev: str = self.cfg.skin_abbreviations[class_idx]
                score: float = float(probs_np[class_idx])

                heatmap: np.ndarray = gradcam.generate_heatmap(
                    input_tensor, int(class_idx)
                )
                overlay: np.ndarray = gradcam.blend_overlay(visual_base_rgb, heatmap)
                overlay_b64: str = self._encode_image(overlay)

                top_findings.append(
                    {
                        "label": label,
                        "abbreviation": abbrev,
                        "class_idx": int(class_idx),
                        "confidence": round(score, 4),
                        "overlay_img": overlay_b64,
                    }
                )

        predicted_class: str = self.cfg.skin_labels[top_indices[0]] if len(top_indices) > 0 else ""

        return {
            "original_img": self._encode_image(visual_base_rgb),
            "top_findings": top_findings,
            "predicted_class": predicted_class,
            "patient_id": Path(image_path).name,
        }

    async def async_run_diagnostic(
        self, image_path: str, top_k: int = 3
    ) -> Dict[str, Any]:
        """Execute the diagnostic pass asynchronously by offloading CPU work to a thread.

        PyTorch inference and Grad-CAM backward passes are CPU-bound operations
        that must not block the uvicorn event loop.

        Args:
            image_path (str): The file path to the input image.
            top_k (int, optional): The number of top predictions to generate. Defaults to 3.

        Returns:
            Dict[str, Any]: A dictionary containing the original image, findings, predicted class, and patient ID.
        """
        return await asyncio.to_thread(self.run_diagnostic, image_path, top_k)
