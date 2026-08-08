# MediScanX - Backend Microservices Architecture

![Python](https://img.shields.io/badge/python-3.12+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg?logo=fastapi)
![PyTorch](https://img.shields.io/badge/PyTorch-2.0+-EE4C2C.svg?logo=pytorch)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Build](https://img.shields.io/badge/build-passing-brightgreen.svg)

Welcome to the central backend repository for **MediScanX**, a highly optimized, multi-container microservices ecosystem designed for advanced multi-modal medical diagnostics. Our architecture seamlessly blends state-of-the-art Computer Vision (CV), Signal Processing, and LLM-driven Agentic Orchestration into a unified clinical engine.

---

## Table of Contents

- [MediScanX - Backend Microservices Architecture](#mediscanx---backend-microservices-architecture)
    - [Table of Contents](#table-of-contents)
    - [Architectural Topology \& Traffic Flow](#architectural-topology--traffic-flow)
    - [Core Technology Stack](#core-technology-stack)
    - [Unified Engineering Standards](#unified-engineering-standards)
    - [Getting Started](#getting-started)
        - [Prerequisites](#prerequisites)
        - [Global Orchestration](#global-orchestration)
        - [Local Development](#local-development)
    - [Continuous Integration (CI/CD)](#continuous-integration-cicd)
    - [Engineering Team](#engineering-team)

---

## Architectural Topology & Traffic Flow

The MediScanX backend strictly follows an API Gateway pattern. All external frontend traffic hits the `gateway_backend` first. Acting as a secure perimeter, the Gateway validates incoming requests and enforces zero-trust authentication before proxying traffic into the isolated internal network of downstream inference and orchestration microservices.

| Microservice          | Role               | Description                                                                                                                                            |
| :-------------------- | :----------------- | :----------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`gateway_backend`** | Security & Routing | The central FastAPI reverse proxy. Handles CORS, rate-limiting, chunked upload limits, and zero-trust asymmetric authentication (Supabase ES256/JWKS). |
| **`agent_service`**   | Orchestration      | LangGraph-powered stateful orchestration engine. Manages RAG (clinical guidelines retrieval) and streams Server-Sent Events (SSE) back to the client.  |
| **`cxr_service`**     | Medical CV         | PyTorch`DenseNet121` inference engine. Classifies Chest X-Rays and generates spatial GradCAM heatmap overlays.                                         |
| **`ecg_service`**     | Signal Processing  | PyTorch`CNN-BiLSTM` inference engine. Processes 12-lead ECG signals for anomaly classification and 1D saliency mapping.                                |
| **`skin_service`**    | Medical CV         | PyTorch`MobileNetV3` inference engine. Specializes in dermatological lesion classification and spatial heatmaps.                                       |

---

## Core Technology Stack

- **Python 3.12+**: The foundation of our modern, asynchronous ecosystem.
- **FastAPI & Uvicorn**: High-performance, asynchronous web frameworks driving every container.
- **PyTorch**: Deep learning backend for all medical inference architectures.
- **LangGraph**: Stateful, cyclic graph orchestration for our clinical LLM agent.
- **Supabase**: Providing stateless, edge-ready ES256 asymmetric JWT authentication.
- **`uv`**: Lightning-fast, Rust-backed Python dependency and virtual environment management.

---

## Unified Engineering Standards

To maintain predictability and robustness across a complex multi-container deployment, the MediScanX monorepo strictly enforces "Single-Developer Architectural Consistency."

- **Strict Type-Hinting**: Every endpoint, dependency, schema, and utility function is fully and strictly typed.
- **Domain-Driven Design (DDD)**: Each microservice features a custom exception hierarchy (e.g., `GatewayBaseException`, `AgentBaseException`) representing exact domain failures.
- **Unified JSON Error Envelopes**: A global `ExceptionRegistry` inside every container ensures that all errors, regardless of origin, serialize into an identical JSON payload structure: `{"error": true, "type": "...", "message": "...", "context": {...}}`.
- **Clinical Documentation Tone**: All Google-style docstrings and README matrices utilize a mature, objective, and professional clinical voice.

---

## Getting Started

### Prerequisites

Ensure the following tools are installed on your host machine:

- **Docker** & **Docker Compose**
- **`uv`** (Astral's lightning-fast Python package manager)
- **Python 3.12+**

### Global Orchestration

To boot the entire MediScanX backend ecosystem locally, utilize Docker Compose from the root directory:

```bash
docker compose up --build
```

This command will spin up the `gateway_backend` alongside the downstream inference and orchestration services, automatically handling the internal DNS routing.

### Local Development

For active development, profiling, or running test suites, you can run individual microservices natively on your host machine using `uv`.

Navigate into the desired service directory and execute:

```bash
cd gateway_backend
uv sync
uv run fastapi dev src/app/main.py
```

> [!TIP]
> **Deep-Dive Schemas & Configurations**
> Developers _must_ read the localized `README.md` file within each microservice directory (e.g., `cxr_service/README.md`). These individual documents contain the granular Input/Output matrices, exact JSON payload schemas, and required `.env` variables specific to that service.

---

## Continuous Integration (CI/CD)

The MediScanX monorepo employs a stringent, automated GitHub Actions pipeline across all microservices to enforce code quality and prevent regressions.

- **Branch Protection**: Direct pushes to `dev` and `main` are strictly blocked. All architectural and feature changes must pass through Pull Requests.
- **Automated Validation**: On every Pull Request, individual service pipelines trigger automatically. They execute:
    - Mocked `pytest` suites to validate domain logic without external IO overhead.
    - Multi-stage Docker build dry-runs to ensure containerization integrity before merging.
- **Dependency Caching**: Workflows utilize `astral-sh/setup-uv` with Docker BuildKit cache mounts to optimize pipeline execution times.

## Running tests

Each service has its own test suite. From the repository root you can run the gateway tests with `uv`:

```bash
cd backend/gateway_backend && uv run pytest -q
```

Service-specific tests live under `backend/*/tests` and are exercised by the service CI workflows.
