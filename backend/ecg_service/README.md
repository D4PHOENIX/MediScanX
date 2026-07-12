# ECG Diagnostic Microservice

## Domain Summary
The ECG Service is a production-grade microservice for **12-lead Electrocardiograms (ECGs) inference**. It utilizes a specialized CNN-BiLSTM hybrid architecture optimized for identifying and classifying cardiac pathologies. The service provides high-performance, asynchronous diagnostics coupled with 1D Grad-CAM visual explainability to assist medical professionals in identifying cardiac anomalies.

## Quickstart Local Reproducibility

To run the application locally, use `uv` for lightning-fast dependency management and execution:

```bash
# Navigate to the service root
cd ecg_service

# Install dependencies and start the service on port 8002
PYTHONPATH=src uv run uvicorn app.main:app --host 0.0.0.0 --port 8002
```

The API will be available at `http://localhost:8002`. Interactive Swagger documentation can be accessed at `http://localhost:8002/docs`.

## Payload Schemas Matrix

The service exposes a multipart endpoint `/predict` for ECG signal analysis.

### Input Schema (Multipart FormData)

| Field | Type | Required | Description |
|---|---|---|---|
| `files` | `image/jpeg`, `image/jpg`, `image/png`, `application/octet-stream` | **Yes** | A single photograph of a printed ECG strip, or two WFDB files (`.dat` and `.hea`). |
| `xai` | `boolean` | No | Set to `true` to return a Grad-CAM heatmap visualization (default: `false`). |

### Output JSON Payload Schema

| Field | Type | Description |
|---|---|---|
| `predictions` | `array` | List of top-k classification predictions. |
| `predictions[].label` | `string` | Full clinical name of the predicted class (e.g., "NORM"). |
| `predictions[].class_idx` | `int` | Internal integer index of the predicted class. |
| `predictions[].confidence` | `float` | Softmax probability score. |
| `predictions[].overlay_img` | `string` | Base64-encoded PNG of the 1D Grad-CAM heatmap overlaid on the original signal. |
| `predicted_class` | `string` | The highest confidence clinical label prediction. |
| `predicted_confidence` | `float` | The highest confidence clinical label score. |
| `gradcam_overlay` | `string` | Base64-encoded PNG of the highest confidence Grad-CAM heatmap. |
| `inference_time_ms` | `float` | Total time taken for inference. |
| `patient_id` | `string` | Parsed from the incoming file name (for correlation). |

## Custom Error/Exception Mapping Framework

The microservice employs a strict Domain-Driven Design (DDD) exception architecture. Domain exceptions are completely decoupled from the HTTP layer and are mapped to standard JSON error responses via a global `ExceptionRegistry`.

To maintain perfect documentation parity, the Exception Hierarchy relies on the exact exception class names created by the Optimization Subagent.

| Exception Class | HTTP Status | Trigger / Description |
|---|---|---|
| `SignalProcessingError` | `422 Unprocessable Entity` | General pipeline failure during digital/optical processing. |
| `SignalLengthMismatchError` | `422 Unprocessable Entity` | Raised when the ECG signal length does not match expected length. |
| `InvalidLeadCountError` | `400 Bad Request` | Raised when the number of ECG leads is invalid. |
| `ECGFileReadError` | `422 Unprocessable Entity` | Supplied WFDB or image files cannot be opened or parsed. |
| `InvalidSignalShapeError` | `422 Unprocessable Entity` | Preprocessed tensor violates the required `(1, 12, 500)` shape. |
| `ECGInferenceError` | `500 Internal Server Error` | General inference failure (PyTorch or generic execution errors). |
| `ONNXInferenceError` | `500 Internal Server Error` | Inference fails inside the ONNX Runtime session. |
| `ECGModelNotFoundError` | `503 Service Unavailable` | Startup fails because ONNX/PyTorch model artifacts are missing. |
| `ECGEngineNotReadyError`| `503 Service Unavailable` | A request is made before the ML engine has fully initialized. |
