# ecg_service

ECG inference for MediScanX. It turns a **photo of a 12-lead paper ECG** into digital signals, classifies them into the five PTB-XL superclasses with a dual-branch CNN-BiLSTM, and returns a 1-D Grad-CAM saliency overlay. It also accepts raw WFDB recordings. Internal only; the gateway calls it.

FastAPI · Python 3.11 · PyTorch / PyTorch Lightning · OpenCV · SciPy · wfdb · onnxruntime (optional)

## Pipeline

```
photo ─► grid suppression ─► layout slicing (12 lead bands) ─► waveform extraction ─► resample
      ─► morphology (12 × 250) + rhythm (lead II, 1 × 1000) + amplitudes (12)
      ─► DualBranchECGClassifier ─► per-class sigmoid + thresholds ─► 1-D Grad-CAM
```

**Digitiser** (`src/app/engine/digitizer/`):

| Stage | File | What it does |
|---|---|---|
| Grid suppression | `grid_suppression.py` | removes the pink/red paper grid |
| Layout slicing | `layout_slicer.py` | finds lead bands and crops the 12 leads (footer excluded) |
| Waveform extraction | `waveform_extractor.py` | traces the ink column by column, enforces continuity, measures coverage |
| Orchestration | `pipeline.py` | runs the stages and fails closed |

Each lead must reach `min_coverage = 0.65` (65 % of columns with a detected trace). If any lead fails, the request returns **422** with the failed leads and retake guidance instead of classifying a degraded signal.

## Model

`DualBranchECGClassifier` (`src/app/models/cnn_bilstm.py`):

| Branch | Input | Layers | Output |
|---|---|---|---|
| Morphology | 12 leads × 250 samples (2.5 s @ 100 Hz) | Conv1d 64 → 128 → 256 + BiLSTM | 128-d |
| Rhythm | lead II × 1000 samples (10 s) | Conv1d 32 → 64 → 128 + BiLSTM | 64-d |
| Amplitude | 12 peak-to-peak voltages | Linear 12 → 32 + BN + ReLU | 32-d |
| Fusion head | concat 224 | Linear 128 → dropout → 5 logits | NORM · MI · STTC · CD · HYP |

The amplitude branch restores absolute voltage, which signal normalisation removes and which hypertrophy depends on.

| | |
|---|---|
| Training data | PTB-XL (21,837 records) + Georgia 12-lead (10,344), trained jointly |
| Thresholds | NORM 0.51 · MI 0.43 · STTC 0.49 · CD 0.52 · HYP 0.50 (fold 9) |
| Validation (fold 9) | macro AUROC 0.8940, macro F1 0.7049 |
| External (Chapman-Shaoxing, 9,758 records) | macro AUROC 0.7370; normal-vs-abnormal AUROC 0.7627, precision 0.9538, sensitivity 0.6029 |
| Latency | ~35 ms per recording on CPU |

Fold 9 also chose the thresholds, so the validation figures are optimistic; Chapman-Shaoxing is fully external. There is no on-device ECG model.

## Endpoints

| Method | Path | Notes |
|---|---|---|
| POST | `/predict` | multipart: either `file` (PNG/JPEG photo) or `wfdb_files` (a `.dat` + `.hea` pair); form `top_k` (default 5); query `xai` (default true) |
| GET | `/healthz` | 200 once a model backend is loaded |
| GET | `/` | service metadata |

```json
{
  "predictions": [
    {"label": "MI", "class_idx": 1, "confidence": 0.81, "above_threshold": true,
     "threshold": 0.43, "overlay_img": "<base64 PNG>", "overlay_lead": "II"}
  ],
  "predicted_class": "MI",
  "confidence": 0.81,
  "gradcam_overlay": "<base64 PNG>",
  "inference_time_ms": 35.2,
  "patient_id": "<temp file name>"
}
```

## Configuration

| Variable | Default (container) |
|---|---|
| `ECG_CKPT_PATH` | `/models/mediscanx-multisource-epoch=00-val_macro_f1=0.7049.ckpt` |
| `ECG_ONNX_PATH` | optional ONNX export; used only if present |
| `CLASSIFICATION_THRESHOLD` | fallback threshold |
| `DEVICE` | `cpu` or `cuda` |

Compose mounts `weights/` at `/models` and a named volume for digitiser diagnostics.

## Run and test

```bash
uv sync --all-extras
uv run uvicorn app.main:app --app-dir src --port 8002
curl -F "file=@ecg.jpg" http://localhost:8002/predict

uv run pytest -q                      # 15 passed
```

## Known limitations

- The digitiser recovers no physical time base from the paper grid; the coverage gate is an engineering parameter.
- The full photo-to-diagnosis path is not evaluated end to end; reported metrics are on digital signals.
- Per-site threshold recalibration is needed to raise external sensitivity.
