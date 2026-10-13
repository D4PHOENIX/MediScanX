# skin_service

Skin-lesion inference for MediScanX: an EfficientNet-B0 trained on dermoscopy and smartphone photos, with a two-stage oncology triage (a melanoma safety gate first, then other skin cancers) and a Grad-CAM overlay. Internal only; the gateway calls it.

FastAPI · Python 3.11 · PyTorch · torchvision · OpenCV · Pillow

## Model

| | |
|---|---|
| Architecture | EfficientNet-B0 backbone, 8-way head, softmax |
| Classes | actinic keratoses (akiec), basal cell carcinoma (bcc), benign keratosis (bkl), dermatofibroma (df), melanoma (mel), melanocytic nevi (nv), vascular lesions (vasc), normal skin |
| Training data | HAM10000 (dermoscopy) + PAD-UFES-20 (smartphone) + normal-skin photos |
| Input | 224 × 224 RGB |
| Preprocessing | EXIF orientation fix → Otsu region-of-interest crop for uncropped phone photos (20 % margin) → resize → ImageNet normalisation |
| Explainability | Grad-CAM on the last backbone block, blended softly so surrounding skin stays visible |

| Held-out cohort (1,380 images) | |
|---|---|
| Top-1 accuracy · macro AUROC | 0.8333 · 0.9770 |
| Malignant (mel + bcc + akiec) sensitivity · benign specificity | 0.9171 · 0.8311 |
| Melanoma alert sensitivity | 0.8571 (90 / 105) |
| Cancers classified as normal skin | 0 of 350 |
| Top-1 by source: HAM10000 · PAD-UFES-20 (phone) · normal | 0.840 · 0.685 · 0.994 |

## Triage

Applied in priority order in `engine/diagnostic_engine.py`:

| Condition | `triage_level` | `melanoma_alert` |
|---|---|---|
| P(melanoma) ≥ 0.20, whatever the top class | `URGENT_REFERRAL` | `true` |
| P(bcc) ≥ 0.50 or P(akiec) ≥ 0.50 | `SPECIALIST_REVIEW` | `false` |
| Top class is normal skin | `HEALTHY_SKIN` | `false` |
| Otherwise | `ROUTINE_MONITORING` | `false` |

The 0.20 gate trades precision (melanoma precision 0.51) for sensitivity: a melanoma alert is a prompt for specialist review, not a diagnosis. The gateway escalates alerted scans.

## Endpoints

| Method | Path | Notes |
|---|---|---|
| POST | `/predict` | multipart `file` (JPEG/PNG); query `top_k` (default 3), `xai` (default true) |
| GET | `/healthz` | 200 once the model is loaded |
| GET | `/` | service metadata |

```json
{
  "top_findings": [
    {"label": "Melanocytic nevi", "abbreviation": "nv", "class_idx": 6, "confidence": 0.71, "overlay_img": "<base64 PNG>"}
  ],
  "predicted_class": "Melanocytic nevi",
  "triage_level": "URGENT_REFERRAL",
  "melanoma_alert": true,
  "clinical_note": "High-risk melanoma probability threshold (P = 0.24 >= 0.20) triggered. ...",
  "original_img": "<base64 PNG>",
  "patient_id": "<temp file name>"
}
```

## Configuration

| Variable | Default |
|---|---|
| `SKIN_WEIGHTS_PATH` | `/weights/skin_multidomain_weights.pth` |
| `MELANOMA_TRIAGE_THRESHOLD` | `0.20` |
| `ENABLE_OTSU_ROI` | `true` |
| `NUM_CLASSES`, `IMAGE_SIZE` | `8`, `224` |
| `DEVICE` | auto (`cuda` if available) |

## Run and test

```bash
uv sync --all-extras
uv run uvicorn app.main:app --app-dir src --port 8003
curl -F "file=@lesion.jpg" http://localhost:8003/predict

uv run pytest -q                      # 37 passed, 2 skipped
```

## On-device model

The phone runs a LiteRT FP32 export of the same weights (`frontend/assets/models/skin_model/skin_multidomain_fp32.tflite`, 15.3 MB) with bit-exact parity to PyTorch and ~31 ms per image on CPU. `src/app/models/mobilenet_v3.py` is an earlier experiment kept for reference.

## Known limitations

No evaluation on an institution outside the training sources; phone photos (0.685 top-1) remain the weakest domain; dermatofibroma (13) and vascular (5) results rest on very few cases.
