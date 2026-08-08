# MediScanX

<div align="center">

![CI](https://img.shields.io/badge/CI-GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![PyTorch](https://img.shields.io/badge/PyTorch-EE4C2C?logo=pytorch&logoColor=white)
![Postgres](https://img.shields.io/badge/PostgreSQL%2017-4169E1?logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)

</div>

## One-line summary

Multimodal AI diagnostics for low-resource clinical settings: CXR, ECG and
skin‑lesion inference with explainability overlays, retrieval‑grounded
assistance, and QR-based referral handoff.

## Overview

The system is designed for environments with unreliable connectivity: compute
runs on-device where feasible and in the cloud where required. Outputs are
auditable — Grad‑CAM overlays are stored and their absence is explicit — and
clinician access is governed by explicit consent rows in the database.

## Key capabilities

- Multimodal inference: independent services for `cxr`, `ecg`, and `skin`.
- Optical ECG digitisation: reconstructs 12‑lead traces from photographs and
  reports per‑lead coverage when input quality is insufficient.
- Explainability: Grad‑CAM overlays stored alongside scans; `xai_status`
  distinguishes `none`, `generated`, `skipped_edge` and `failed`.
- Retrieval‑augmented assistant: LangGraph agent backed by a pgvector corpus.
- Reports & handoff: immutable PDF reports with QR tokens that grant
  time‑bounded clinician access.

## Architecture (high level)

```
											 ┌─────────────────┐
											 │  Flutter client │
											 └────────┬────────┘
																│ JWT
											 ┌────────▼────────┐
											 │ gateway_backend │  auth · persistence · storage
											 │    (FastAPI)    │  the only public surface
											 └────────┬────────┘
						 ┌──────────────────┼──────────────────┐
						 │                  │                  │
		 ┌───────▼──────┐   ┌───────▼──────┐   ┌───────▼──────┐
		 │ cxr_service  │   │ ecg_service  │   │ skin_service │
		 │  DenseNet121 │   │  CNN-BiLSTM  │   │  classifier  │
		 └──────────────┘   └──────────────┘   └──────────────┘
						 │
		 ┌───────▼───────┐        ┌──────────────────────────┐
		 │ agent_service │◄──────►│  Supabase / PostgreSQL   │
		 │   LangGraph   │        │  pgvector · RLS · storage │
		 └───────────────┘        └──────────────────────────┘
```

The `gateway_backend` is the only service exposed to clients; inference
services are internal-only. The `agent_service` manages RAG and conversational
flows; storage and authorization are centralised in the database/storage layer.

## Repository structure

```
MediScanX/
├── backend/            # FastAPI gateway and microservices (inference + agent)
├── frontend/           # Flutter client and on-device models
├── schema/             # Database schema and schema README
├── ml_pipeline/        # Model training/quantization scripts and notebooks
├── legacy/             # Older prototype code
└── README.md
```

## Getting started

Prerequisites: Docker & Docker Compose, a Supabase project (Postgres + Storage),
and a Gemini API key for agent features.

1. Copy environment example:

```bash
cp .env.example .env
```

2. Apply the database schema to your Supabase/Postgres instance:

```bash
psql "$DATABASE_URL" -f schema/0001_baseline_schema.sql
```

3. Build and start the stack (from `backend/`):

```bash
docker compose up -d --build
curl -i localhost:8000/api/v1/health/healthz  # expect 200
```

Notes:

- Model weights are not committed — place them in each service's `weights/` folder.
- Each service has its own tests and CI workflows under `backend/*/tests`.

### Running gateway tests

```bash
cd backend/gateway_backend && uv run pytest -q
```

## API surface

All routes are prefixed with `/api/v1` and require a Supabase JWT unless noted.

See `docs/` for full request/response schemas.

## Security & data model

- Consent is a row in `care_relationships` and is enforced by `has_care_access()`.
- Row-level security (RLS) protects public tables; the service role bypasses RLS.
- Storage buckets are private and path‑based authorization is used (patient UUID
  is the leading path segment).

## Scope & limitations

- Temporal tracking compares diagnosis labels, not quantitative lesion sizes.
- Cross‑modality correlation is textual and constrained — clinicians should
  review generated content.
- Optical ECG digitisation can fail on poor photos; the system reports
  per‑lead coverage rather than producing a degraded diagnosis.

## Tech stack

API: FastAPI · Python 3.11 · `uv`
Inference: PyTorch · DenseNet121 · CNN‑BiLSTM · OpenCV
Explainability: Grad‑CAM
Agent: LangGraph · Gemini
Retrieval: pgvector · MedCPT embeddings · HNSW
Data: Supabase · PostgreSQL 17 · PowerSync
Client: Flutter · TensorFlow Lite
Infrastructure: Docker Compose · GitHub Actions

## Contributors

- Daud Noman
- Muhammad Arham Shafaat
- Wassam Khan
- Engr. Zubair Ahmad — supervisor
