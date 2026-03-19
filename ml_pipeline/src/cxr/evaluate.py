"""
Standalone execution script for End-to-End CXR Pipeline Evaluation.
Instantiates the full MediScanX inference architecture, loads optimized weights 
by stripping compiler prefixes, and processes a batch of test patients to 
render the visual diagnostic dashboard.
"""
import os
import sys
import torch
import pandas as pd
from collections import OrderedDict

# Adjust path to allow imports from the 'src' directory
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.cxr.config.inference_config import CXRInferenceConfig
from src.cxr.data.preprocessor import CXRInferencePreprocessor
from src.cxr.models.densenet_cihmlc import DenseNet121_CIHMLC
from src.cxr.utils.explainability import GradCAMPlusPlus
from src.cxr.engine.diagnostic_engine import CXRDiagnosticEngine

def load_production_model(cfg: CXRInferenceConfig) -> torch.nn.Module:
    """
    Factory function to instantiate the model and safely load weights, 
    stripping any compiler or multi-GPU prefixes.
    """
    print(f"Allocating CIHMLC architecture on {cfg.device}...")
    model = DenseNet121_CIHMLC(num_classes=cfg.num_classes, pretrained=False)
    
    try:
        raw_state_dict = torch.load(cfg.model_weights_path, map_location=cfg.device, weights_only=True)
        
        if 'model_state_dict' in raw_state_dict:
            raw_state_dict = raw_state_dict['model_state_dict']
            
        # Clean compiler and parallel hardware prefixes
        clean_state_dict = OrderedDict()
        for k, v in raw_state_dict.items():
            name = k.replace('_orig_mod.', '').replace('module.', '')
            clean_state_dict[name] = v
            
        model.load_state_dict(clean_state_dict)
        print(f"SUCCESS: Model weights perfectly mapped and loaded!")
        return model

    except FileNotFoundError as e:
        raise FileNotFoundError(
            f"CRITICAL ERROR: Weights not found at {cfg.model_weights_path}.\n"
            f"Please check your path configuration."
        ) from e
    except RuntimeError as e:
        raise RuntimeError(f"Weight mapping failed: {e}") from e

def run_academic_evaluation(cfg: CXRInferenceConfig, num_samples: int = 3) -> None:
    """
    Simulates a production environment by orchestrating the engine 
    and running a batch evaluation for academic visualization.
    """
    print("Initializing MediScanX Pipeline Components...")
    
    # Initialize Components
    preprocessor = CXRInferencePreprocessor(cfg)
    xai_engine = GradCAMPlusPlus(cfg)
    cxr_model = load_production_model(cfg)
    
    diagnostic_engine = CXRDiagnosticEngine(cfg, cxr_model, preprocessor, xai_engine)
    
    # Load Clinical Records
    try:
        print(f"Loading clinical records from: {cfg.csv_test_path}")
        df_test = pd.read_csv(cfg.csv_test_path)
        
        sample_patients = df_test.sample(n=num_samples, random_state=42)
        print(f"Executing diagnostic pass on {len(sample_patients)} patient records...\n" + "-"*60)
        
        # Execution Loop
        for index, row in sample_patients.iterrows():
            relative_path = row['Path'].replace('CheXpert-v1.0-small/', '')
            full_image_path = os.path.join(cfg.kaggle_dataset_root, relative_path)
            
            if os.path.exists(full_image_path):
                # Extract ground truth seamlessly
                true_labels = [
                    float(row[label]) if pd.notna(row[label]) else 0.0 
                    for label in cfg.CHEXPERT_LABELS
                ]
                
                # Execute Core & Shell
                api_payload = diagnostic_engine.run_diagnostic(full_image_path, top_k=4)
                diagnostic_engine.visualize_evaluation_dashboard(api_payload, true_labels)
                
            else:
                print(f"Warning: Image file not found at {full_image_path}.")

    except FileNotFoundError:
        print(f"CRITICAL ERROR: Could not find the test CSV at {cfg.csv_test_path}.")
    except KeyError as e:
        print(f"CSV Parsing Error: Column {e} not found in the dataset.")


if __name__ == "__main__":
    global_cfg = CXRInferenceConfig()
    run_academic_evaluation(global_cfg, num_samples=3)