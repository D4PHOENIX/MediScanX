# cxr_service

Chest X-ray inference for MediScanX: a DenseNet-121 with squeeze-and-excitation and a clinically-inspired hierarchical multi-label head, returning the most likely CheXpert findings with calibrated thresholds and a Grad-CAM++ overlay. Internal only; the gateway calls it.

FastAPI · Python 3.11 · PyTorch · torchvision · OpenCV

## Model

| | |
|---|---|
| Architecture | `DenseNet121_CIHMLC`: ImageNet DenseNet-121 → ReLU → SE block (1024 channels, reduction 16) → global average pool → dropout 0.5 → Linear(1024, 20) |
| Outputs | 20 sigmoids: 14 CheXpert findings + 6 hierarchical parents (Abnormal, Fluid Accumulation, Missing Lung Tissue, Other, Cardiac, Opacity). The service reports the 14 findings only |
| Input | 1 × 3 × 320 × 320 |
| Preprocessing | auto-crop black borders (threshold 15) → CLAHE (clip 3.0, 10 × 10 tiles) → pad to square → resize 320 (INTER_AREA) → ImageNet normalisation; identical to training |
| Thresholds | per finding, Youden's J on the validation split (0.44–0.63); the first 14 values of `best_thresholds.npy` |
| Explainability | Grad-CAM++ on the SE-weighted 1024-channel maps, blended over the image |
| Training | CheXpert with VisualCheXbert labels, patient-level split, hierarchical BCE (penalty on child > parent), two-stage fine-tuning — `notebooks/03-cxr-densenet-cihmlc-two-stage.ipynb` |

| Evaluation (frozen model) | Macro AUROC |
|---|---|
| CheXpert held-out, 14 findings, 4,862 images | 0.9001 [0.8939–0.9060] |
| CheXpert radiologist consensus, 202 images | 0.8900 |
| VinDr-CXR · Indiana Open-i · NIH ChestX-ray14 | 0.9057 · 0.8658 · 0.7275 |

Abnormal-triage operating point on the held-out split: sensitivity 0.8508, specificity 0.9019. External thresholds need site calibration (`notebooks/04-cxr-external-validation.ipynb`).

## Endpoints

| Method | Path | Notes |
|---|---|---|
| POST | `/predict` | multipart `file` (JPEG/PNG; anything else → 415); query `top_k` (default 5), `xai` (default true) |
| GET | `/healthz` | 200 once the model and thresholds are loaded |
| GET | `/` | service metadata |

```json
{
  "top_findings": [
    {"label": "Pleural Effusion", "class_idx": 10, "confidence": 0.9132, "overlay_img": "<base64 PNG>"}
  ],
  "predicted_diagnoses": ["Pleural Effusion", "Support Devices"],
  "original_img": "<base64 PNG>",
  "patient_id": "<temp file name>"
}
```

`top_findings` is sorted by probability; `predicted_diagnoses` lists the findings above their thresholds. The gateway takes the first finding as `ai_diagnosis`, stores the overlay and drops `original_img`.

## Configuration

| Variable | Default (container) |
|---|---|
| `CXR_WEIGHTS_PATH` | `/weights/best_densenet_cihmlc.pth` |
| `CXR_THRESHOLDS_PATH` | `/weights/best_thresholds.npy` |
| `HEATMAP_BETA`, `COLORMAP` | overlay blending |

Place both files in `weights/`; Compose mounts it at `/weights`. Weights load with `strict=True`; a missing file stops start-up with an explicit error.

## Run and test

```bash
uv sync --all-extras
uv run uvicorn app.main:app --app-dir src --port 8001
curl -F "file=@xray.jpg" "http://localhost:8001/predict?top_k=3"

uv run pytest -q                      # 12 passed (weights mocked)
```

## On-device model

The phone runs a TFLite INT8 post-training-quantised export of this checkpoint (`frontend/assets/models/cxr_model/cxr_model.tflite`, ~194 ms per image on CPU, no overlay). INT8 loses accuracy on this architecture; an FP16 export that matches PyTorch exactly is the planned replacement (`notebooks/05-cxr-densenet-cihmlc-quantization.ipynb`).
