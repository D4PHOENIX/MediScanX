# MediScanX

**Multimodal medical diagnostics on a smartphone: chest X-ray, ECG and skin-lesion analysis that works offline, explains itself, and hands the case to a specialist through a consent-based QR referral.**

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![PyTorch](https://img.shields.io/badge/PyTorch-EE4C2C?logo=pytorch&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-1C3C3C)
![Flutter](https://img.shields.io/badge/Flutter-02569B?logo=flutter&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL_17-4169E1?logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker_Compose-2496ED?logo=docker&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

Final Year Project 2026 · BS Computer Science · IISAT University, Gujranwala

> MediScanX is decision support. Every result is a retrospective evaluation on public datasets; nothing here is a clinical diagnosis.

---

## Contents

- [MediScanX](#mediscanx)
    - [Contents](#contents)
    - [What it does](#what-it-does)
    - [Results](#results)
    - [Architecture](#architecture)
    - [Repository layout](#repository-layout)
    - [Quick start: install the app](#quick-start-install-the-app)
    - [Running the backend](#running-the-backend)
    - [Building the app](#building-the-app)
    - [API surface](#api-surface)
    - [Security and consent model](#security-and-consent-model)
    - [Testing and CI](#testing-and-ci)
    - [Team](#team)
    - [Licence and data](#licence-and-data)

---

## What it does

A health worker at a Basic Health Unit, or a patient, photographs a scan with the phone:

| Step        | What happens                                                                                                |
| ----------- | ----------------------------------------------------------------------------------------------------------- |
| **Capture** | Chest X-ray, ECG printout or skin lesion, from the camera or the gallery                                    |
| **Analyse** | In the cloud for all three modalities; **on the device with no network** for chest X-ray and skin           |
| **Explain** | Grad-CAM++ (X-ray), Grad-CAM (skin) and 1-D Grad-CAM (ECG) overlays, stored privately with the record       |
| **Triage**  | Severity derived from the finding first and the confidence second; a melanoma alert at P ≥ 0.20             |
| **Track**   | History and trend per modality, with the transition between consecutive scans                               |
| **Fuse**    | Two or more modalities combined into one weighted risk tier                                                 |
| **Ask**     | A LangGraph assistant grounded in a 49,875-passage medical corpus (MedCPT retrieval), with citations        |
| **Refer**   | A PDF report with a signed QR code; a doctor who scans it gets 7 days of access that the patient can revoke |

Offline results wait in a local outbox and sync to the cloud record when the connection returns, without duplicates and without losing the only copy of the image.

## Results

Frozen models, stored thresholds, no retraining on any evaluation set.

| Model       | Architecture                                                                                   | In-distribution                                                                                        | External                                                                     |
| ----------- | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------- |
| Chest X-ray | DenseNet-121 + squeeze-and-excitation, hierarchical multi-label head (14 findings + 6 parents) | macro AUROC **0.9001** [0.8939–0.9060], CheXpert held-out; **0.8900** on the radiologist consensus set | VinDr-CXR **0.9057**, Indiana Open-i **0.8658**, NIH ChestX-ray14 **0.7275** |
| ECG         | Dual-branch CNN-BiLSTM (12-lead morphology, lead-II rhythm, lead amplitudes)                   | macro AUROC **0.8940**, PTB-XL + Georgia validation                                                    | Chapman-Shaoxing **0.7370** (never seen in training)                         |
| Skin        | EfficientNet-B0, 7 lesion classes + normal skin                                                | top-1 **0.8333**, macro AUROC **0.9770**; malignant sensitivity **0.9171**                             | —                                                                            |

On-device CPU latency: skin **31 ms**, chest X-ray **194 ms**. System testing: **124 / 124** cases passed on Android devices; **479** automated backend tests pass.

## Architecture

```
Flutter app (Android)
  ├─ on-device TFLite / LiteRT: chest X-ray (INT8), skin (FP32)
  ├─ PowerSync local SQLite  ◄──sync──►  PowerSync  ◄──logical replication──  Supabase Postgres
  └─ HTTPS ─► Cloudflare Tunnel ─► gateway_backend  (FastAPI · :8000 · the only public service)
                                       ├─► cxr_service    DenseNet-121 + SE           :8001
                                       ├─► ecg_service    dual-branch CNN-BiLSTM      :8002
                                       ├─► skin_service   EfficientNet-B0             :8003
                                       └─► agent_service  LangGraph · Gemini · MedCPT  (no published port)

Supabase: PostgreSQL 17 · pgvector (HNSW, halfvec 768) · Auth (ES256 JWT) · private Storage · RLS · pg_cron
```

- The **gateway** validates the Supabase JWT against the project's JWKS, proxies to the internal services, uploads images and overlays, derives severity, persists results, generates reports and handles QR claims.
- Each **inference service** owns one model behind the same `POST /predict` contract. Adding a modality means adding a container and a label set; nothing in the core changes.
- The **agent service** runs a LangGraph state graph with nine tools and a Postgres checkpointer, streaming answers to the app over Server-Sent Events.
- **Supabase** is the system of record: 11 tables, row-level security on every table, two private buckets, the PowerSync publication and a scheduled consent-expiry job.

## Repository layout

```
MediScanX/
├── backend/
│   ├── docker-compose.yml     five services + Cloudflare Tunnel
│   ├── .env.example           all variables the stack needs
│   ├── gateway_backend/       public API: auth, persistence, storage, reports, QR claims
│   ├── agent_service/         LangGraph assistant and RAG
│   ├── cxr_service/           chest X-ray inference + Grad-CAM++
│   ├── ecg_service/           ECG digitiser + inference + 1-D Grad-CAM
│   └── skin_service/          skin-lesion inference + Grad-CAM + melanoma triage
├── frontend/                  Flutter client and on-device models
├── schema/                    SQL that rebuilds the database
├── notebooks/                 CXR training, external validation, quantisation, RAG corpus seeding
├── .github/workflows/         one CI workflow per backend service
└── LICENSE
```

Each folder above (except `.github`) has its own README with the details.

## Quick start: install the app

1. Download the APK from the [latest release](https://github.com/D4PHOENIX/MediScanX/releases/latest) (arm64-v8a; Android 7.0 / API 24 or newer).
2. Allow installation from unknown sources when prompted and install it.
3. Register as a patient or a doctor, verify the emailed code and sign in.

The release build talks to the production backend at `https://mediscanx.app`. Put the phone in airplane mode to try the offline path: chest X-ray and skin still run on the device and sync when the network returns.

## Running the backend

**Requirements:** Docker with Compose, a Supabase project, a PowerSync instance, a Gemini API key, and the model weights (not committed because of their size).

```bash
# 1. Database: rebuild the full schema on a new Supabase project
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f schema/mediscanx_schema.sql

# 2. Weights: place them in each service's weights/ folder (see the service READMEs)

# 3. Configuration
cd backend
cp .env.example .env        # fill in Supabase, database, Gemini and token secrets

# 4. Start
docker compose up -d --build
curl -i http://localhost:8000/api/v1/health/healthz      # expect 200
```

All services bind to `127.0.0.1`. The `cloudflared` container publishes the gateway when `CLOUDFLARE_TUNNEL_TOKEN` is set. Full details: [`backend/README.md`](backend/README.md) and [`schema/README.md`](schema/README.md).

## Building the app

```bash
cd frontend
cp .env.example .env        # SUPABASE_URL, SUPABASE_ANON_KEY, POWERSYNC_URL, API_BASE_URL (ends in /api/v1)
flutter pub get
dart run build_runner build --delete-conflicting-outputs
flutter build apk --release --split-per-abi
```

Details: [`frontend/README.md`](frontend/README.md).

## API surface

Every route is served by the gateway under `/api/v1` and requires a Supabase bearer token unless marked public.

| Method                    | Path                                                                       | Purpose                                                                 |
| ------------------------- | -------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| POST                      | `/cxr/predict`, `/ecg/predict`, `/skin/predict`                            | Cloud inference; stores the image, overlay and result                   |
| POST                      | `/sync/edge-inference`                                                     | Upload a result computed on the device (idempotent)                     |
| GET                       | `/scans/history`, `/scans/trends`                                          | Scan history and per-modality trend for the caller                      |
| GET                       | `/scans/triage`                                                            | Doctor's queue of consenting patients' scans, worst first               |
| DELETE                    | `/scans/{scan_id}`                                                         | Delete one of the caller's scans and its stored objects                 |
| POST                      | `/scans/claim`                                                             | Redeem a report QR token (creates or extends a 7-day care relationship) |
| POST                      | `/fusion/fuse`                                                             | Weighted multimodal risk score                                          |
| POST                      | `/agent/chat`                                                              | Assistant conversation, streamed as Server-Sent Events                  |
| POST · GET · GET · DELETE | `/reports/generate`, `/reports`, `/reports/download/{id}`, `/reports/{id}` | PDF reports with QR codes                                               |
| GET · POST                | `/patients/care-relationships`, `/patients/care-relationships/revoke`      | Patient views and revokes doctor access                                 |
| GET                       | `/patients/{id}`, `/patients/{id}/scans`, `/doctors/{id}`                  | Profiles and a patient's scans (consent-checked)                        |
| GET                       | `/health/healthz`                                                          | Liveness (public)                                                       |
| POST                      | `/webhooks/supabase`                                                       | Webhook acknowledgement endpoint                                        |

Two public routes sit at the domain root: `/.well-known/assetlinks.json` (Android App Links) and `/claim` (QR landing page). Request and response shapes are in [`backend/gateway_backend/README.md`](backend/gateway_backend/README.md) and in the OpenAPI docs at `/docs` when the gateway runs locally.

## Security and consent model

- **Identity** comes from Supabase Auth only. The gateway verifies ES256 tokens against the JWKS and never trusts a user id sent in a form or a query.
- **Row-level security** is enabled on all 11 tables. A doctor reaches a patient's data only through `has_care_access()`, which requires an active, unexpired row in `care_relationships`.
- **Consent** is created by a QR claim or a request/accept flow, expires after 7 days on the claim path, can be revoked by the patient at any time, and is never reactivated by an old QR code.
- **Storage** buckets are private. Overlays and images are fetched through authenticated URLs carrying the user's own token; reports through short-lived signed URLs.
- **Secrets** live in environment files that are never committed. The gateway's database pool uses the service role, so every gateway query is scoped to the token's identity in code; this is tested directly.

## Testing and CI

```bash
cd backend/<service> && uv sync --all-extras && uv run pytest -q
cd frontend && flutter analyze && flutter test
```

| Suite           | Passed         |
| --------------- | -------------- |
| gateway_backend | 329            |
| agent_service   | 86             |
| skin_service    | 37 (2 skipped) |
| ecg_service     | 15             |
| cxr_service     | 12             |

Each backend service has a GitHub Actions workflow, filtered to its own directory, that runs the test suite and a Docker build dry-run on every pull request into `dev` and `main`. The 124-case system test record (accounts, cloud scans, offline operation, explainability, history, fusion, assistant, reports, clinician access, concurrency, API contract) was executed on Android devices against the production backend.

## Team

| Member                 | Role                                                                        |
| ---------------------- | --------------------------------------------------------------------------- |
| Daud Noman             | Project lead · backend architecture · chest X-ray model · assistant and RAG |
| Muhammad Arham Shafaat | Flutter client · UI/UX · offline sync                                       |
| Wassam Khan            | ECG and skin models                                                         |
| Engr. Zubair Ahmad     | Supervisor                                                                  |

## Licence and data

Source code is released under the [MIT License](LICENSE). The models were trained on public research datasets (CheXpert, PTB-XL, Georgia 12-lead, HAM10000, PAD-UFES-20) and evaluated on NIH ChestX-ray14, VinDr-CXR, Indiana Open-i and Chapman-Shaoxing, each under its own terms; several restrict commercial use. No dataset is redistributed in this repository, and released weights are for research use only.
