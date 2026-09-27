"""Synchronous diagnostic engine that coordinates preprocessing, inference and XAI."""

import asyncio
import base64
from pathlib import Path
from typing import Any, Dict, List

import cv2
import numpy as np
import torch
import torch.nn.functional as F

from app.core.config import SkinInferenceConfig
from app.explainability.gradcam import SkinGradCAM
from app.engine.preprocessor import SkinPreprocessor


class SkinDiagnosticEngine:
    """Orchestration engine for skin-lesion inference, oncology triage, and Grad-CAM visualisation.

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
        """Initializes the SkinDiagnosticEngine."""
        self.cfg: SkinInferenceConfig = cfg
        self.model: torch.nn.Module = model
        self.preprocessor: SkinPreprocessor = preprocessor
        self.xai_engine: SkinGradCAM = xai_engine

    @staticmethod
    def _encode_image(img: np.ndarray) -> str:
        """Convert a numpy image (RGB uint8) to a base64-encoded PNG string."""
        _, buffer = cv2.imencode('.png', cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
        return base64.b64encode(buffer).decode('utf-8')

    def determine_triage(self, probs_np: np.ndarray, top_pred_idx: int) -> tuple[str, bool, str]:
        """Compute clinical oncology triage category, alert flag, and clinical note."""
        mel_idx = self.cfg.skin_abbreviations.index("mel") if "mel" in self.cfg.skin_abbreviations else 4
        mel_prob = float(probs_np[mel_idx])
        bcc_idx = self.cfg.skin_abbreviations.index("bcc") if "bcc" in self.cfg.skin_abbreviations else 1
        bcc_prob = float(probs_np[bcc_idx])
        akiec_idx = self.cfg.skin_abbreviations.index("akiec") if "akiec" in self.cfg.skin_abbreviations else 0
        akiec_prob = float(probs_np[akiec_idx])

        top_class_abbrev = self.cfg.skin_abbreviations[top_pred_idx] if 0 <= top_pred_idx < len(self.cfg.skin_abbreviations) else ""

        # Priority 1: Melanoma Safety Alert Gate (P >= 0.20)
        if mel_prob >= self.cfg.melanoma_triage_threshold:
            triage_level = "URGENT_REFERRAL"
            melanoma_alert = True
            clinical_note = f"High-risk melanoma probability threshold (P = {mel_prob:.2f} >= {self.cfg.melanoma_triage_threshold:.2f}) triggered. Urgent specialist evaluation required."
        elif bcc_prob >= 0.50 or akiec_prob >= 0.50:
            triage_level = "SPECIALIST_REVIEW"
            melanoma_alert = False
            clinical_note = "High probability of non-melanoma cutaneous malignancy. Specialist biopsy recommended."
        elif top_class_abbrev == "normal":
            triage_level = "HEALTHY_SKIN"
            melanoma_alert = False
            clinical_note = "Unaffected healthy skin. Zero pathological lesion patterns detected."
        else:
            triage_level = "ROUTINE_MONITORING"
            melanoma_alert = False
            clinical_note = "Predominantly benign clinical features observed. Continue standard surveillance."

        return triage_level, melanoma_alert, clinical_note

    def run_diagnostic(self, image_path: str, top_k: int = 3, use_gradcam: bool = True) -> Dict[str, Any]:
        """Execute a complete diagnostic pass with two-stage oncology triage."""
        # 1. Preprocessing with ROI localization
        input_tensor, visual_base_rgb = self.preprocessor.process(image_path)
        input_tensor = input_tensor.to(self.cfg.device)

        # 2. Forward pass for probabilities
        with torch.no_grad():
            try:
                logits: torch.Tensor = self.model(input_tensor)
            except Exception as e:
                from app.core.exceptions import ModelInferenceError
                raise ModelInferenceError("PyTorch forward pass failed") from e

        probs: torch.Tensor = F.softmax(logits, dim=1)
        probs_np: np.ndarray = probs.squeeze().cpu().numpy()

        top_indices: np.ndarray = np.argsort(probs_np)[::-1][:top_k]

        # 3. Two-Stage Clinical Oncology Triage Logic
        top_pred_idx = int(top_indices[0]) if len(top_indices) > 0 else 0
        triage_level, melanoma_alert, clinical_note = self.determine_triage(probs_np, top_pred_idx)

        # 4. Build findings (with Grad-CAM overlays)
        top_findings: List[Dict[str, Any]] = []
        if use_gradcam:
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
        else:
            for class_idx in top_indices:
                label = self.cfg.skin_labels[class_idx]
                abbrev = self.cfg.skin_abbreviations[class_idx]
                score = float(probs_np[class_idx])
                top_findings.append(
                    {
                        "label": label,
                        "abbreviation": abbrev,
                        "class_idx": int(class_idx),
                        "confidence": round(score, 4),
                    }
                )

        predicted_class: str = self.cfg.skin_labels[top_indices[0]] if len(top_indices) > 0 else ""

        return {
            "original_img": self._encode_image(visual_base_rgb),
            "top_findings": top_findings,
            "predicted_class": predicted_class,
            "patient_id": Path(image_path).name,
            "triage_level": triage_level,
            "melanoma_alert": melanoma_alert,
            "clinical_note": clinical_note,
        }

    async def async_run_diagnostic(
        self, image_path: str, top_k: int = 3, use_gradcam: bool = True
    ) -> Dict[str, Any]:
        """Execute diagnostic pass asynchronously by offloading to executor thread."""
        return await asyncio.to_thread(self.run_diagnostic, image_path, top_k, use_gradcam)
