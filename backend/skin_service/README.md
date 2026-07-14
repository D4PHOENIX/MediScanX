# Skin Lesion Diagnostic Service

## Domain Summary
The Skin Service is a production-grade microservice for **MobileNetV3 Lesion inference**. It utilizes a specialized MobileNetV3 backbone optimized for 7-class dermatological lesion classification (e.g., Actinic keratoses, Basal cell carcinoma, Melanoma). The service provides high-performance, asynchronous diagnostics coupled with Grad-CAM visual explainability to assist medical professionals in identifying skin anomalies.

## Quickstart: Local Reproducibility (using `uv run`)

To run the application locally, use `uv` for lightning-fast dependency management and execution:

```bash
# Navigate to the service root
cd skin_service

# Install dependencies and start the service on port 8003
PYTHONPATH=src uv run uvicorn app.main:app --host 0.0.0.0 --port 8003
```

The API will be available at `http://localhost:8003`. Interactive Swagger documentation can be accessed at `http://localhost:8003/docs`.

## Input / Output Matrix (Payload Schemas)

The service exposes a multipart endpoint `/predict` for skin lesion analysis.

### Input Schema (Multipart FormData)

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | `image/jpeg`, `image/png`, `image/jpg` | **Yes** | The skin lesion image upload. |
| `top_k` | `int` | No | Number of top findings to return (default: `3`). |

### Output JSON Payload Schema

| Field | Type | Description |
|---|---|---|
| `original_img` | `string` | Base64-encoded PNG representation of the original image. |
| `top_findings` | `array` | List of top-k classification predictions. |
| `top_findings[].label` | `string` | Full clinical name of the predicted class (e.g., "Melanoma"). |
| `top_findings[].abbreviation` | `string` | ISIC abbreviation code (e.g., "mel"). |
| `top_findings[].class_idx` | `int` | Internal integer index of the predicted class (0-6). |
| `top_findings[].confidence` | `float` | Softmax probability score. |
| `top_findings[].overlay_img` | `string` | Base64-encoded PNG of the Grad-CAM heatmap overlaid on the original image. |
| `predicted_class` | `string` | The highest confidence clinical label prediction. |
| `patient_id` | `string` | Parsed from the incoming file name (for correlation). |

## Custom Error Mapping Framework

The microservice employs a strict Domain-Driven Design (DDD) exception architecture. Domain exceptions are completely decoupled from the HTTP layer and are mapped to standard JSON error responses via a global `ExceptionRegistry`.

To maintain perfect documentation parity, the Exception Hierarchy relies on the exact exception class names created by the Optimization Subagent.

| Exception Class | HTTP Status | Trigger / Description |
|---|---|---|
| `InvalidImageDimensionError` | `422 Unprocessable Entity` | Raised when the preprocessed tensor does not match the expected input shape for the MobileNetV3 architecture. |
| `UnreadableImageFormatError` | `422 Unprocessable Entity` | Raised when the preprocessing pipeline (e.g., OpenCV) cannot read or decode the supplied image file. |
| `ModelInferenceError` | `500 Internal Server Error` | PyTorch model forward pass, gradient computation, or Grad-CAM heatmap generation failed unexpectedly. |
| `SkinEngineNotReadyError` | `503 Service Unavailable` | The skin diagnostic engine is still initializing its weights in the background or is otherwise unavailable. |
| `SkinModelNotFoundError` | `500 Internal Server Error` | Raised when the model weights file is missing at the expected path. |
| `ImageProcessingError` | `422 Unprocessable Entity` | Raised when the preprocessing pipeline cannot handle a supplied image. |
