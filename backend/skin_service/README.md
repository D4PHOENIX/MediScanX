# Skin Lesion Diagnostic Service

## Domain Summary

The Skin Service is a production-grade microservice for **multi-domain skin lesion and healthy skin inference**. It utilizes an **EfficientNet-B0** backbone trained across HAM10000 (dermoscopy), PAD-UFES-20 (smartphone clinical macro photography), and unlesioned healthy skin controls for **8-class** dermatological classification (Actinic keratoses, Basal cell carcinoma, Benign keratosis, Dermatofibroma, Melanoma, Normal skin, Melanocytic nevi, Vascular lesion). The service features an automated Otsu adaptive saliency ROI preprocessor, a two-stage oncology safety triage engine ($P(\text{mel}) \ge 0.20 \rightarrow \text{URGENT\_REFERRAL}$), and Grad-CAM visual explainability.

## Quickstart: Local Reproducibility (using `uv run`)

To run the application locally, use `uv` for lightning-fast dependency management and execution:

```bash
# Navigate to the service root
cd skin_service

# Install dependencies and start the service on port 8003
PYTHONPATH=src uv run uvicorn app.main:app --host 0.0.0.0 --port 8003
```

The API will be available at `http://localhost:8003`. Interactive Swagger documentation can be accessed at `http://localhost:8003/docs`.

## Docker Deployment

The Skin Service uses a multi-stage Docker build optimized with `uv` for dependency caching. It runs as a non-root user for enhanced security.

To build and run the Docker container locally:

```bash
cd skin_service
docker build -t mediscanx/skin-service .
docker run -p 8003:8003 mediscanx/skin-service
```

## CI/CD Pipeline

The repository includes a GitHub Actions pipeline (`.github/workflows/skin-service.yml`) that triggers on pull requests to the `dev` and `main` branches. It enforces:

- A `pytest` suite ensuring all core logic is intact.
- Optimal PyTorch CPU wheel caching utilizing `astral-sh/setup-uv`.
- A dry-run multi-stage Docker build that runs a smoke test import chain to catch regressions.

## Input / Output Matrix (Payload Schemas)

The service exposes a multipart endpoint `/predict` for skin lesion analysis.

### Input Schema (Multipart FormData)

| Field   | Type                                   | Required | Description                                      |
| ------- | -------------------------------------- | -------- | ------------------------------------------------ |
| `file`  | `image/jpeg`, `image/png`, `image/jpg` | **Yes**  | The skin lesion image upload.                    |
| `top_k` | `int`                                  | No       | Number of top findings to return (default: `3`). |

### Output JSON Payload Schema

| Field                         | Type      | Description                                                                 |
| ----------------------------- | --------- | --------------------------------------------------------------------------- |
| `original_img`                | `string`  | Base64-encoded PNG representation of the original image (or ROI crop).      |
| `top_findings`                | `array`   | List of top-k classification predictions.                                   |
| `top_findings[].label`        | `string`  | Full clinical name of the predicted class (e.g., "Melanoma", "Normal skin"). |
| `top_findings[].abbreviation` | `string`  | ISIC / clinical abbreviation code (e.g., "mel", "normal").                  |
| `top_findings[].class_idx`    | `int`     | Internal integer index of the predicted class (0-7).                        |
| `top_findings[].confidence`   | `float`   | Softmax probability score.                                                  |
| `top_findings[].overlay_img`  | `string`  | Base64-encoded PNG of the Grad-CAM heatmap overlaid on the original image.  |
| `predicted_class`             | `string`  | The highest confidence clinical label prediction.                           |
| `patient_id`                  | `string`  | Parsed from the incoming file name (for correlation).                       |
| `triage_level`                | `string`  | Clinical triage level: `URGENT_REFERRAL`, `SPECIALIST_REVIEW`, `HEALTHY_SKIN`, `ROUTINE_MONITORING`. |
| `melanoma_alert`              | `boolean` | Flag set to `true` whenever $P(\text{mel}) \ge 0.20$ safety threshold is triggered. |
| `clinical_note`               | `string`  | Clinical recommendation rationale for the patient and healthcare provider. |

## Custom Error Mapping Framework

The microservice employs a strict Domain-Driven Design (DDD) exception architecture. Domain exceptions are completely decoupled from the HTTP layer and are mapped to standard JSON error responses via a global `ExceptionRegistry`.

To maintain perfect documentation parity, the Exception Hierarchy relies on the exact exception class names created by the Optimization Subagent.

| Exception Class              | HTTP Status                 | Trigger / Description                                                                                         |
| ---------------------------- | --------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `InvalidImageDimensionError` | `422 Unprocessable Entity`  | Raised when the preprocessed tensor does not match the expected input shape for the MobileNetV3 architecture. |
| `UnreadableImageFormatError` | `422 Unprocessable Entity`  | Raised when the preprocessing pipeline (e.g., OpenCV) cannot read or decode the supplied image file.          |
| `ModelInferenceError`        | `500 Internal Server Error` | PyTorch model forward pass, gradient computation, or Grad-CAM heatmap generation failed unexpectedly.         |
| `SkinEngineNotReadyError`    | `503 Service Unavailable`   | The skin diagnostic engine is still initializing its weights in the background or is otherwise unavailable.   |
| `SkinModelNotFoundError`     | `500 Internal Server Error` | Raised when the model weights file is missing at the expected path.                                           |
| `ImageProcessingError`       | `422 Unprocessable Entity`  | Raised when the preprocessing pipeline cannot handle a supplied image.                                        |
