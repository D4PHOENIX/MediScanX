# Agent Service

## Domain Summary

The Agentic AI Orchestrator (`agent_service`) serves as the central reasoning engine for MediScanX. Utilizing a cyclic tool-calling architecture powered by `langgraph` and `langchain-google-genai`, it orchestrates complex medical query workflows. It coordinates downstream multi-modal inference services (`cxr_service`, `ecg_service`, `skin_service`), executes clinical RAG (Retrieval-Augmented Generation) against a Supabase pgvector database, and computes temporal disease progression. Communication with the API Gateway is handled efficiently via Server-Sent Events (SSE), streaming reasoning chunks and UI triggers asynchronously.

## Quickstart: Local Reproducibility

### Prerequisites

- Python 3.10+
- `uv` (for fast Python package installation)
- Docker & Docker Compose
- Supabase (Local or Cloud) instance with `pgvector` enabled

### Local Setup

```bash
# Sync dependencies and create virtual environment automatically
uv sync

# Set required environment variables
export GEMINI_API_KEY="your_api_key_here"
export GOOGLE_MODEL="gemini-3.5-flash"
export DATABASE_URL="postgresql://..."
export SUPABASE_URL="https://xyz.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="eyJhbGci..."
export CXR_SERVICE_URL="http://localhost:8001/predict"
export ECG_SERVICE_URL="http://localhost:8002/predict"
export SKIN_SERVICE_URL="http://localhost:8003/predict"

# Start the development server using uv run
PYTHONPATH=src uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8005
```

### Docker Usage

The service is containerized using a multi-stage Docker build optimized with `uv` for fast, cached dependency installations.

```bash
docker build -t mediscanx-agent-service .
docker run -p 8005:8005 --env-file .env mediscanx-agent-service
```

### CI/CD Pipeline

A GitHub Actions pipeline (`.github/workflows/agent-service.yml`) automatically runs on pull requests to the `dev` and `main` branches.
It includes two jobs:

1. **Test**: Runs the `pytest` suite using `uv`.
2. **Docker Build**: Validates the multi-stage Docker build (dry-run, no push) and performs a smoke test on the entrypoint.

## Input / Output Matrix (Payload Schemas)

The primary interaction mode with the `agent_service` is via the chat streaming endpoint, which utilizes Server-Sent Events (SSE). The Input/Output Matrix below clearly defines the consumption contract.

### Input Schema (`ChatRequest`)

Submitted via HTTP POST to the streaming endpoint `/chat`.

```json
{
    "messages": [{ "role": "user", "content": "Analyze chest X-ray for patient 123" }],
    "patient_id": "123",
    "current_scan_id": "scan-xyz",
    "execution_step": "initial",
    "multimodal_metadata": {}
}
```

### Server-Sent Events (SSE) Output Matrix

The server responds with a `text/event-stream` returning JSON payload chunks. Clients must parse the `event` type and the corresponding JSON `data`.

| Event Type   | Description                                                                          | JSON Payload Format                                                                                                                                                                                                                       |
| ------------ | ------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `text`       | Streamed text chunks from the LLM reasoning process.                                 | `{"text": "I am analyzing the patient's records... "}`                                                                                                                                                                                    |
| `ui_trigger` | Fired when the agent invokes a tool or returns an inference result to update the UI. | `{"type": "tool_call", "id": "call_abc123", "tool": "run_cxr_inference", "args": {"image_path_or_id": "scan-xyz"}}` OR `{"type": "cxr_result", "findings": "Cardiomegaly detected"}` OR `{"type": "pdf_generated", "url": "https://..."}` |
| `error`      | Terminal or non-terminal error events encountered during execution.                  | `{"error": true, "type": "ContextRetrievalError", "message": "Failed to fetch vector embeddings.", "context": {}}` OR `{"detail": "Unexpected error string"}`                                                                             |
| `done`       | Signals the end of the SSE stream.                                                   | `{}`                                                                                                                                                                                                                                      |

## Custom Error Mapping Framework

The application implements a robust exception hierarchy rooted in `AgentBaseException` to categorize and handle orchestrator-level failures efficiently.

| Exception Class              | Description                                                             |
| ---------------------------- | ----------------------------------------------------------------------- |
| `AgentBaseException`         | Base domain exception for the Agentic AI Orchestrator.                  |
| `LLMInferenceError`          | The LLM provider returned an error or timed out.                        |
| `ToolExecutionError`         | A registered tool failed during execution.                              |
| `UpstreamServiceUnavailable` | A downstream medical API is unreachable or returned a non-200 response. |
| `AgentStateCorrupted`        | The agent's internal state graph is inconsistent.                       |
| `LLMProviderError`           | The LLM provider encountered an error.                                  |
| `StateGraphExecutionError`   | Error during state graph execution.                                     |
| `ContextRetrievalError`      | Error retrieving clinical context or guidelines.                        |
| `AgentEngineNotReadyError`   | The agent engine is not ready to process requests.                      |
