# CXR Diagnostic Service

## Domain Summary
The CXR Diagnostic Service is a production-grade microservice for **DenseNet-121 Chest X-Ray (CXR) inference**. It utilizes a specialized DenseNet-121 backbone optimized for 14-class CheXpert diagnostic labels (e.g., Cardiomegaly, Pleural Effusion). The service provides high-performance, asynchronous diagnostics coupled with Grad-CAM++ visual explainability to assist medical professionals in identifying thoracic anomalies. It utilizes finely calibrated, per-class decision thresholds for robust binary diagnostic flags.

## Quickstart: Local Reproducibility

To run the application locally, use `uv` for lightning-fast dependency management and execution:

```bash
# Navigate to the service root
cd cxr_service

# Install dependencies and start the service on port 8001
PYTHONPATH=src uv run uvicorn app.main:app --host 0.0.0.0 --port 8001
```

The API will be available at `http://localhost:8001`. Interactive Swagger documentation can be accessed at `http://localhost:8001/docs`.

## Input / Output Matrix

The service exposes a multipart endpoint `/predict` for chest X-ray analysis, as well as `/healthz` for health checks and `/` for service metadata.

### `POST /predict`

#### Input Payload Schema (Multipart FormData)

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | `image/jpeg`, `image/png`, `image/jpg` | **Yes** | The chest X-ray image upload. |
| `top_k` | `int` | No | Number of top findings to return (default: `5`). |

#### Output Payload Schema (JSON)

| Field | Type | Description |
|---|---|---|
| `original_img` | `string` | Base64-encoded PNG representation of the original image. |
| `top_findings` | `array` | List of top-k classification predictions. |
| `top_findings[].label` | `string` | Full clinical name of the predicted class (e.g., "Cardiomegaly"). |
| `top_findings[].class_idx` | `int` | Internal integer index of the predicted class. |
| `top_findings[].confidence` | `float` | Sigmoid probability score. |
| `top_findings[].overlay_img` | `string` | Base64-encoded PNG of the Grad-CAM++ heatmap overlaid on the original image. |
| `predicted_diagnoses` | `array` | List of clinical labels where confidence exceeded the per-class threshold. |
| `patient_id` | `string` | Parsed from the incoming file name (for correlation). |

### `GET /healthz`

#### Output Payload Schema (JSON)

| Field | Type | Description |
|---|---|---|
| `status` | `string` | Health status (e.g., "healthy"). |

### `GET /`

#### Output Payload Schema (JSON)

| Field | Type | Description |
|---|---|---|
| `service` | `string` | Service name metadata. |
| `docs` | `string` | Path to the interactive API documentation. |

## Custom Error Mapping Framework

The microservice employs a strict Domain-Driven Design (DDD) exception architecture. Domain exceptions are completely decoupled from the HTTP layer and are mapped to standard JSON error responses via a global `ExceptionRegistry`.

### Error Response Schema (JSON)

| Field | Type | Description |
|---|---|---|
| `error` | `boolean` | Always `true` for domain exceptions. |
| `type` | `string` | The exact Python exception class name. |
| `message` | `string` | A human-readable description of the error. |
| `context` | `object` | Additional key-value pairs providing context about the failure. |

### Exception Hierarchy & HTTP Status Matrix

| Exception Class | HTTP Status | Trigger / Description |
|---|---|---|
| `ImageProcessingError` | `422 Unprocessable Entity` | Raised when the preprocessing pipeline cannot handle the supplied image. |
| `ImageReadError` | `422 Unprocessable Entity` | Raised when OpenCV fails to decode the supplied image file. |
| `InvalidTensorShapeError` | `422 Unprocessable Entity` | Raised when the preprocessed tensor shape does not match the expected [1, 3, H, W]. |
| `ModelInferenceError` | `500 Internal Server Error` | PyTorch model forward pass, gradient computation, or Grad-CAM++ heatmap generation failed unexpectedly. |
| `CXRModelNotFoundError` | `500 Internal Server Error` | Raised when the PyTorch weights file is missing. |
| `CXREngineNotReadyError` | `503 Service Unavailable` | The CXR diagnostic engine is still initializing its weights in the background or is otherwise unavailable. |
