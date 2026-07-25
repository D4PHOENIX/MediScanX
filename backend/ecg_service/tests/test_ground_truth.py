import pytest
import pytest_asyncio
import numpy as np
from typing import Dict, Any
from app.engine.preprocessor import ECGPreprocessor
from app.core.config import Settings
from .vendor.ecg_renderer import generate_ecg_image
import cv2
import os

# Mark as integration test, excluded from fast unit tests
pytestmark = pytest.mark.integration

def get_ground_truth_segment(full_record: np.ndarray, lead_idx: int, col_idx: int, num_cols: int = 4, target_len: int = 500) -> np.ndarray:
    """Extracts the time-aligned ground truth segment for a specific lead column and resamples to target length."""
    total_samples = full_record.shape[1]
    samples_per_col = total_samples // num_cols
    
    start_idx = col_idx * samples_per_col
    end_idx = start_idx + samples_per_col
    
    segment = full_record[lead_idx, start_idx:end_idx]
    
    from scipy.signal import resample
    resampled_segment = resample(segment, target_len)
    
    mean_val = np.mean(resampled_segment)
    std_val = np.std(resampled_segment) + 1e-8
    return (resampled_segment - mean_val) / std_val

def compute_metrics(extracted: np.ndarray, truth: np.ndarray) -> Dict[str, float]:
    # Pearson correlation
    num = np.sum((extracted - np.mean(extracted)) * (truth - np.mean(truth)))
    den = np.sqrt(np.sum((extracted - np.mean(extracted))**2) * np.sum((truth - np.mean(truth))**2))
    r = num / den if den > 1e-8 else 0.0
    
    # NRMSE
    rmse = np.sqrt(np.mean((extracted - truth)**2))
    nrmse = rmse / (np.max(truth) - np.min(truth) + 1e-8)
    
    # Peak-to-peak ratio
    p2p_ext = np.max(extracted) - np.min(extracted)
    p2p_truth = np.max(truth) - np.min(truth)
    amp_ratio = p2p_ext / (p2p_truth + 1e-8)
    
    return {'r': r, 'nrmse': nrmse, 'amp_ratio': amp_ratio}

def _check_weights_exist() -> bool:
    return os.path.exists("./weights/ecg_v2_12lead.ckpt") or os.path.exists("./weights/ecg_v2_12lead.onnx")

@pytest.mark.asyncio
@pytest.mark.skipif(not _check_weights_exist(), reason="Model weights not found. Skipping integration test.")
async def test_baseline_harness():
    cfg = Settings(
        onnx_model_path="./weights/ecg_v2_12lead.onnx",
        pytorch_ckpt_path="./weights/ecg_v2_12lead.ckpt"
    )
    preprocessor = ECGPreprocessor(cfg)
    
    from app.engine.ecg_engine import ECGEngine
    engine = ECGEngine(cfg=cfg)
    try:
        await engine.initialize()
    except Exception as e:
        print(f"Failed to load real model: {e}")
        return
        
    # Generate synthetic 10-second record (12, 5000)
    t = np.linspace(0, 10, 5000)
    signal = np.zeros((12, 5000), dtype=np.float32)
    for i in range(12):
        # A simple pulse every 1 second
        pulse = np.exp(-((t % 1.0) - 0.5)**2 / 0.01) * (1.0 - i*0.05)
        signal[i] = pulse + np.random.randn(5000) * 0.05
        
    # Write wfdb files to evaluate baseline WFDB prediction
    import torch
    # mock wfdb is not easy to write, so let's mock process_wfdb in preprocessor
    # to return our synthetic tensor for the ground truth test.
    tensor_gt = torch.tensor(signal, dtype=torch.float32).unsqueeze(0)
    
    from unittest.mock import patch
    with patch('app.engine.diagnostic_engine.ECGPreprocessor.process_wfdb', return_value=(tensor_gt, signal)):
        # Run ground-truth WFDB prediction
        result_gt = await engine.predict("fake.dat", input_type="wfdb", top_k=1)
        gt_class = result_gt["predicted_class"]
        gt_conf = result_gt["predicted_confidence"]
        
    layouts = ['3-band', '4-band']
    dpis = [150, 300, 600]
    thicknesses = [1.0, 3.0]
    
    print("\n--- Baseline Results ---")
    print(f"Ground Truth Prediction: {gt_class} (Conf: {gt_conf:.2f})")
    print("---------------------------------------------------------")
    
    leads = [
        ['I', 'aVR', 'V1', 'V4'],
        ['II', 'aVL', 'V2', 'V5'],
        ['III', 'aVF', 'V3', 'V6']
    ]
    lead_idx_map = {
        'I': 0, 'II': 1, 'III': 2,
        'aVR': 3, 'aVL': 4, 'aVF': 5,
        'V1': 6, 'V2': 7, 'V3': 8,
        'V4': 9, 'V5': 10, 'V6': 11
    }
    
    for layout in layouts:
        for dpi in dpis:
            for thick in thicknesses:
                print(f"Config: {layout} | {dpi} DPI | Thick: {thick}")
                img = generate_ecg_image(signal, layout=layout, dpi=dpi, trace_thickness=thick)
                cv2.imwrite("/tmp/test_harness_temp.png", img)
                
                try:
                    result_img = await engine.predict("/tmp/test_harness_temp.png", input_type="image", top_k=1)
                    img_class = result_img["predicted_class"]
                    img_conf = result_img["predicted_confidence"]
                    
                    match = (img_class == gt_class)
                    conf_delta = img_conf - gt_conf
                    print(f"  Diagnosis: {'AGREE' if match else 'DISAGREE'} | img={img_class} gt={gt_class} | delta_conf={conf_delta:+.2f}")
                    
                    # Compute metrics
                    tensor, extracted_signals = preprocessor.process_image("/tmp/test_harness_temp.png")
                    print("  Status: Extracted successfully.")
                    
                    for row in range(3):
                        for col in range(4):
                            lead_name = leads[row][col]
                            idx = lead_idx_map[lead_name]
                            ext = extracted_signals[idx]
                            truth = get_ground_truth_segment(signal, idx, col)
                            metrics = compute_metrics(ext, truth)
                            print(f"    {lead_name}: r={metrics['r']:.2f}, NRMSE={metrics['nrmse']:.2f}, AmpRatio={metrics['amp_ratio']:.2f}")
                            
                except Exception as e:
                    if hasattr(e, 'context') and 'coverage' in e.context:
                        covs = e.context['coverage']
                        min_cov = min(covs.values())
                        max_cov = max(covs.values())
                        print(f"  Status: FAILED-CLOSED (Coverage Gate) | Min={min_cov:.2f}, Max={max_cov:.2f}")
                    else:
                        print(f"  Status: FAILED ({type(e).__name__}): {e}")
                    
if __name__ == "__main__":
    import asyncio
    asyncio.run(test_baseline_harness())
