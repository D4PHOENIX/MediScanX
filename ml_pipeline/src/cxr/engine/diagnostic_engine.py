"""
Core orchestration layer for the MediScanX diagnostic API.
Coordinates the data flow between the radiographic preprocessor, the neural 
network, and the Grad-CAM++ XAI engine. Designed to be stateless and thread-safe 
for concurrent web framework (e.g., FastAPI) deployments, while also providing 
Matplotlib rendering for academic evaluation.
"""
import cv2
import torch
import numpy as np
import matplotlib.pyplot as plt
from typing import Dict, List, Any

from src.cxr.config import CXRInferenceConfig
from src.cxr.data.preprocessor import CXRInferencePreprocessor
from src.cxr.utils.explainability import GradCAMPlusPlus

class CXRDiagnosticEngine:
    """
    Orchestration engine for Chest X-Ray inference and diagnostic visualization.
    
    This engine coordinates the data flow between the preprocessor, the neural network,
    and the interpretability engine to produce evidence-based radiographic assessments.
    """
    def __init__(
        self,
        cfg: CXRInferenceConfig,
        model: torch.nn.Module,
        preprocessor: CXRInferencePreprocessor,
        xai_engine: GradCAMPlusPlus
    ) -> None:
        """
        Initializes the diagnostic engine with its constituent components.

        Args:
            cfg (CXRInferenceConfig): Global configuration for inference settings.
            model (nn.Module): The loaded CIHMLC DenseNet121 model.
            preprocessor (CXRInferencePreprocessor): Component for radiographic standardization.
            xai_engine (GradCAMPlusPlus): Component for spatial feature localization.
        """
        self.cfg = cfg
        self.model = model.to(self.cfg.device)
        self.preprocessor = preprocessor
        self.xai_engine = xai_engine
        self.model.eval()
        
    def run_diagnostic(self, image_path: str, top_k: int=5) -> Dict[str, Any]:
        """
        Executes a complete diagnostic pass on X-ray image.

        Args:
            image_path (str): The path to the raw patient X-ray.
            top_k (int): Number of top pathologies to analyze and generate XAI for.

        Returns:
            Dict [str, Any]: Structure diagnostic payload containing probabilities,
                            the raw image, and Grad-CAM++ overlay arrays.
        
        Raises:
            RuntimeError: If the model forward pass or gradient calculation fails.
        """
        # Apply preprocessing on the raw image to retrieve 4D Tensor and original image
        input_tensor, visual_base_rgb = self.preprocessor.process(image_path)
        input_tensor = input_tensor.to(self.cfg.device)
        
        # Enable gradients for the input tensor as Grad-CAM++ requires the computation graph
        input_tensor.requires_grad = True
        
        # Model Forward Pass
        logits, spatial_features = self.model(input_tensor)
        
        # Probability Computation
        probs = torch.sigmoid(logits).squeeze().detach().cpu().numpy()
        
        # Identify Top-K Predictions
        top_indices = np.argsort(probs)[::-1][:top_k]
        
        # Generate Explainability Evidence
        top_findings = []
        for class_idx in top_indices:
            score = float(probs[class_idx])
            label = self.cfg.CHEXPERT_LABELS[class_idx]
            
            # Generate the specific Grad-CAM++ heatmap for the disease
            heatmap = self.xai_engine.generate_heatmap(logits, spatial_features, class_idx)
            overlay = self.xai_engine.blend_overlay(visual_base_rgb, heatmap)
            
            top_findings.append({
                "label": label,
                "confidence": score,
                "overlay_img": overlay
            })
        
        return {
            "original_img": visual_base_rgb,
            "top_findings": top_findings,
            "patient_id": image_path.split('/')[-1]
        }
        
    def visualize_evaluation_dashboard(self, results: Dict[str, Any], true_labels: List[float]=None) -> None:
        """
        Generates a professional clinical dashboard for academic review and debugging.

        Args:
            results (Dict[str, Any]): The output payload from run_diagnostic().
            true_labels (List[float], optional): Ground truth array [14] from the test set.
                                                Used to cross-reference model accuracy.
        """
        top_findings = results["top_findings"]
        num_plots = len(top_findings) + 1
        
        # Format Ground Truth test for the report header
        gt_text = "Unknown"
        active_gt = []
        if true_labels is not None:
            active_gt = [self.cfg.CHEXPERT_LABELS[i] for i, val in enumerate(true_labels) if val == 1.0]
            gt_text = ", ".join(active_gt) if active_gt else "Healthy (No Findings)"
        
        # Initialize the Academic Figure Layout
        fig, axes = plt.subplots(1, num_plots, figsize=(6 * num_plots, 6))
        fig.suptitle(
            f"MediScanX Clinical Assessment | Patient ID: {results['patient_id']}\n"
            f"Ground Truth: {gt_text}",
            fontsize=20, fontweight='bold', y=1.08
        )
        
        # Panel 1: Original Standardized Radiograph
        axes[0].imshow(results["original_img"], cmap='gray')
        axes[0].set_title("Original Radiograph\n(CLAHE Enhanced)", fontsize=16, fontweight='bold')
        axes[0].axis('off')
        
        # Panels 2 to N: Top-K Grad-CAM++ Heatmaps
        for i, finding in enumerate(top_findings):
            axes[i + 1].imshow(finding["overlay_img"])
            
            label = finding["label"]
            prob = finding["confidence"]
            
            # Add an asterisk if the model correctly identified a ground truth pathology
            match_star = "* " if label in active_gt else ""
            
            # Color-code confidence (Red for high alert, Green for low probability)
            if prob > 0.50:
                text_color = "darkred"
                evidence_type = "Positive Evidence"
            else:
                text_color = "forestgreen"
                evidence_type = "Counter-Evidence"
                
            axes[i + 1].set_title(
                f"{match_star}{label}\nConf: {prob*100:.1f}%\n({evidence_type})",
                fontsize=14, fontweight='bold', color=text_color
            )
            axes[i + 1].axis('off')
            
        plt.tight_layout()
        plt.show()