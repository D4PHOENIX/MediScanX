# MediScanX backend

Five FastAPI services and a Cloudflare Tunnel, orchestrated with Docker Compose. The gateway is the only service a client ever talks to; the four internal services are reachable only on the Compose network.

| Service | Port | Responsibility | README |
|---|---|---|---|
| `gateway_backend` | `127.0.0.1:8000` | Auth, routing, persistence, storage, severity, fusion, reports, QR claims, edge sync | [gateway_backend](gateway_backend/README.md) |
| `agent_service` | internal only | LangGraph assistant, MedCPT retrieval over pgvector, SSE streaming | [agent_service](agent_service/README.md) |
| `cxr_service` | `127.0.0.1:8001` | Chest X-ray: DenseNet-121 + SE, 14 CheXpert findings, Grad-CAM++ | [cxr_service](cxr_service/README.md) |
| `ecg_service` | `127.0.0.1:8002` | ECG: photo digitiser, dual-branch CNN-BiLSTM, 5 superclasses, 1-D Grad-CAM | [ecg_service](ecg_service/README.md) |
| `skin_service` | `127.0.0.1:8003` | Skin: EfficientNet-B0, 8 classes, Grad-CAM, melanoma triage | [skin_service](skin_service/README.md) |
| `cloudflared` | — | Publishes the gateway over HTTPS without opening inbound ports | — |

```
client ──HTTPS──► cloudflared ──► gateway_backend ──┬──► cxr_service
                                       │            ├──► ecg_service
                                       │            ├──► skin_service
                                       │            └──► agent_service ──► Gemini
                                       ▼                       │
                         Supabase (Postgres · Storage · Auth) ◄─┘
```

## Common conventions

- **Python 3.11** in every service, dependencies managed with [`uv`](https://docs.astral.sh/uv/) (`pyproject.toml` + `uv.lock`; `requirements.txt` is exported for Docker).
- **Layout:** `src/app/{api,core,engine|services,models}` plus `tests/`. Routers are thin; logic lives in services and engines.
- **Errors:** each service defines a base exception and an `ExceptionRegistry`, so every failure is returned as the same JSON envelope:
  `{"error": true, "type": "...", "message": "...", "context": {...}}`.
- **Fail loudly:** unknown model labels, unreadable inputs and failed uploads are rejected with an explicit error, never persisted as a default or "normal" result.
- **Health:** every service exposes `GET /healthz`; the gateway's is `GET /api/v1/health/healthz`.

## Running the stack

### 1. Prerequisites

- Docker with the Compose plugin
- A Supabase project with the schema applied (see [`../schema/README.md`](../schema/README.md))
- A Gemini API key
- The model weights, placed in the service `weights/` folders:

| Folder | Files expected |
|---|---|
| `cxr_service/weights/` | `best_densenet_cihmlc.pth`, `best_thresholds.npy` |
| `ecg_service/weights/` | `mediscanx-multisource-epoch=00-val_macro_f1=0.7049.ckpt` (an optional ONNX export can sit alongside it) |
| `skin_service/weights/` | `skin_multidomain_weights.pth` |

The folders are bind-mounted into the containers; the weights are not committed because of their size.

### 2. Configure

```bash
cp .env.example .env
```

| Variable | Used by | Purpose |
|---|---|---|
| `SUPABASE_URL` | gateway, agent | Project URL; also the JWKS issuer |
| `SUPABASE_PUBLISHABLE_KEY` | gateway | Public key for user-scoped clients |
| `SUPABASE_SECRET_KEY` | gateway, agent | Service-role key, server side only |
| `DATABASE_URL` | gateway | Postgres, Supabase **session pooler** (port 5432) |
| `AGENT_DATABASE_URL` | agent | Postgres for the LangGraph checkpointer (session pooler; the transaction pooler breaks prepared statements) |
| `GEMINI_API_KEY`, `GOOGLE_MODEL` | gateway, agent | LLM for the assistant and report impressions |
| `REPORT_TOKEN_SECRET` | gateway | HS256 secret for QR claim tokens |
| `CLAIM_BASE_URL` | gateway | Public claim URL printed in the QR (default `https://mediscanx.app/claim`) |
| `ANDROID_CERT_FINGERPRINTS` | gateway | SHA-256 signing fingerprints served in `assetlinks.json` |
| `SUPABASE_STORAGE_BUCKET` | gateway | Scan image bucket, `scan-images` |
| `MAX_UPLOAD_BYTES`, `ALLOWED_ORIGINS` | gateway | Upload limit and CORS |
| `CLOUDFLARE_TUNNEL_TOKEN` | cloudflared | Optional public ingress |
| `DEV_MODE`, `DEV_TOKEN_SECRET` | gateway, agent | Local testing bypass; keep `DEV_MODE=False` in production |
| `RERANK_ENABLED` | agent | Turns on the MedCPT cross-encoder rerank (off by default) |

Internal URLs (`CXR_SERVICE_URL`, `ECG_SERVICE_URL`, `SKIN_SERVICE_URL`, `AGENT_SERVICE_URL`) are pre-set in `.env.example` for the Compose network. Each service also has its own `.env.example` for running it on its own.

### 3. Start

```bash
docker compose up -d --build
docker compose ps
curl -i http://localhost:8000/api/v1/health/healthz
```

The first build downloads PyTorch, the MedCPT models and the service dependencies and takes several minutes.

### 4. Run one service without Docker

```bash
cd gateway_backend
uv sync --all-extras
uv run uvicorn app.main:app --app-dir src --reload --port 8000
```

The same pattern works for every service (ports 8001–8003 for the inference services, 8005 for the agent).

## Tests

```bash
cd <service>
uv sync --all-extras        # pytest is an optional dependency
uv run pytest -q
```

| Suite | Passed |
|---|---|
| gateway_backend | 329 |
| agent_service | 86 |
| skin_service | 37 (2 skipped) |
| ecg_service | 15 |
| cxr_service | 12 |

Tests mock storage, the database and downstream services; persisted state was verified separately against the live database during system testing.

## Continuous integration

`.github/workflows/` holds one workflow per service, path-filtered to that service's directory and triggered on pull requests into `dev` and `main`. Each runs two jobs: the pytest suite (required to merge) and a Docker build dry-run. Workflows use Python 3.11 and `uv sync --frozen`, which fails if `uv.lock` and `pyproject.toml` disagree. Superseded runs are cancelled.
