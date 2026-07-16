# Gateway Backend

## Domain Summary

The Gateway Backend is the single public-facing entrypoint for all client requests in the MediScanX architecture. It routes these requests to specialized internal services such as the CXR, ECG, Skin, and Agent services. The gateway owns authentication validation against Supabase Auth, handles request routing, performs aggregate health checks, and enforces centralized security policies, offloading heavy modality inference processing to downstream containers.

## Quickstart: Local Reproducibility

To start the gateway service locally using `uv`:

```bash
uv run fastapi dev src/app/main.py
```

To verify that the service is running and healthy:

```bash
curl http://localhost:8000/api/v1/health/healthz
```

## Input / Output Matrix (Payload Schemas)

| Schema Model | Purpose | Attributes |
|--------------|---------|------------|
| `InferenceResponse` | Standardized response contract for diagnostic inference results. | `status`, `predicted_class`, `probabilities`, `xai_image` |
| `HealthResponse` | Standardized health-check response contract. | `status`, `version`, `uptime` |
| `PatientHistoryRequest` | Request payload for querying longitudinal patient diagnostic history. | `patient_id`, `modalities` |
| `RoleMessage` | Data contract representing a single conversational turn in the orchestration chat. | `role`, `content` |
| `ChatRequest` | Request payload for initiating or continuing a chat orchestration session. | `messages`, `patient_id`, `current_scan_id`, `execution_step`, `multimodal_metadata` |

## Custom Error Mapping Framework

The Gateway standardizes all errors returned to the client using a consistent exception hierarchy inherited from `GatewayBaseException`.

| Exception Class | HTTP Status | Trigger Condition |
|-----------------|-------------|-------------------|
| `GatewayBaseException` | 500 | Base exception for all custom gateway errors. |
| `UpstreamServiceError` | 502 | An internal downstream microservice fails, times out, or returns an invalid response. |
| `AuthenticationFailedError` | 401 | Missing, malformed, expired, or invalid JWT from the client. |
| `RateLimitExceededError` | 429 | The client exceeds the allowed number of requests in a given time window. |
| `InvalidPayloadError` | 422 | The incoming request payload violates size limits, schema requirements, or chunking rules. |
