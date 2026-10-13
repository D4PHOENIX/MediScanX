# gateway_backend

The only public service in MediScanX. It authenticates every request, routes inference to the internal model services, stores images and explainability overlays, derives severity, persists results, runs multimodal fusion, generates PDF referral reports and redeems their QR codes, and accepts results computed on the device.

FastAPI · Python 3.11 · asyncpg · supabase-py · httpx · ReportLab · python-jose

## Layout

```
src/app/
├── main.py            app factory and lifespan: httpx client, Supabase client, asyncpg pool, migration guard
├── api/               one router per URL group (thin: validate, then call a service)
├── services/          logic: inference orchestration, persistence, storage, fusion, scans, edge sync, reports, LLM
├── core/              config (pydantic-settings), JWT security, exceptions, Supabase client
├── models/            Pydantic request/response schemas and domain enums
└── utils/             label sets, attribution, XAI URL builder, validation
tests/                 pytest suites (routers, services, security, RLS-sensitive paths)
```

## Start-up

`lifespan()` runs once before any request is served:

1. Validates configuration (the app refuses to start on an invalid `SUPABASE_URL`).
2. Opens one shared `httpx.AsyncClient` for the downstream services.
3. Creates the Supabase async client for Storage.
4. Opens an asyncpg pool (min 2, max 4, `statement_cache_size=0` for the Supabase pooler).
5. **Migration guard:** `SELECT inference_source, storage_path FROM scan_results LIMIT 0` — start-up fails if the schema is missing.

## Authentication

Every protected route depends on `get_current_user`:

- reads the bearer token and requires a `kid` header;
- fetches the project's JWKS (`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`), cached for 15 minutes with a 15-second back-off on failure;
- verifies **ES256**, audience `authenticated` and the project issuer, then returns the user id (`sub`).

Identity is taken only from the token. A `patient_id` that differs from the caller is rejected with 403; `user_id` and `doctor_id` form fields are rejected on the sync route. `DEV_MODE` with `DEV_TOKEN_SECRET` enables a constant-time-compared development token that never persists data.

## Endpoints

All under `/api/v1`.

| Method | Path | Notes |
|---|---|---|
| POST | `/cxr/predict` | multipart `file`; form `top_k`, `xai`. Proxies to cxr_service (30 s timeout), uploads image and overlay, derives severity, inserts the row |
| POST | `/ecg/predict` | as above for ECG (photo of a printout) |
| POST | `/skin/predict` | as above for skin; carries `melanoma_alert` and `triage_level` |
| POST | `/sync/edge-inference` | upload a result computed on the device (see *Edge sync*) |
| GET | `/scans/history` | caller's scans, filterable by modality |
| GET | `/scans/trends` | per-modality trend; `modality` required |
| GET | `/scans/triage` | doctors only: scans of consenting patients, worst first |
| DELETE | `/scans/{scan_id}` | storage objects first, then the row |
| POST | `/scans/claim` | redeem a report QR token |
| POST | `/fusion/fuse` | weighted multimodal risk score |
| POST | `/agent/chat` | SSE proxy to agent_service; streams `text`, `ui_trigger` and `error` events |
| POST | `/reports/generate` | PDF report with an embedded QR claim code |
| GET | `/reports` | reports visible to the caller |
| GET | `/reports/download/{report_id}` | short-lived signed URL |
| DELETE | `/reports/{report_id}` | remove a report and its PDF |
| GET | `/patients/care-relationships` | patient's live doctor relationships |
| POST | `/patients/care-relationships/revoke` | patient ends a relationship |
| GET | `/patients/{patient_id}` · `/patients/{patient_id}/scans` · `/doctors/{doctor_id}` | consent-checked profile reads |
| GET | `/health/healthz` | public liveness probe |
| POST | `/webhooks/supabase` | acknowledgement endpoint |

Domain-root routes: `GET /.well-known/assetlinks.json` (Android App Links, from `ANDROID_CERT_FINGERPRINTS`) and `GET /claim` (QR landing page that hands the token to the app).

## Severity

`ScanPersistenceService.derive_scan_status` decides from the finding first and the confidence second:

| Finding | Confidence | `scan_status` |
|---|---|---|
| Normal label (`No Finding`, `NORM`, `Normal skin`) | any | 0 Normal |
| Abnormal label | < 0.85 | 1 Warning |
| Abnormal label | ≥ 0.85 | 2 High Risk |
| Missing finding or modality | — | 1 Warning |
| Unknown label | — | **HTTP 500, nothing persisted** |

A confidently normal scan can never read as high risk, and an abnormal finding is never stored as normal. A skin result with `melanoma_alert` (P(melanoma) ≥ 0.20) is escalated.

## Fusion

`services/fusion_engine.py` weights each scored modality — ECG 1.5, CXR 1.2, skin 1.0. A normal finding scores 0 but still counts its weight; an abnormal one scores `confidence × weight`. The overall score is the weighted mean, and a risk tier is produced **only when at least two modalities are scored**: LOW < 0.30 ≤ MODERATE < 0.60 ≤ HIGH < 0.85 ≤ CRITICAL. Unknown labels and out-of-range confidences are reported as `unscored`, never guessed. The same logic exists in `agent_service/src/app/agent/tools/fusion.py`; the two must change together.

## Reports and QR claims

`POST /reports/generate` builds an A4 PDF with ReportLab (findings, overlays and a hedged LLM impression that is omitted if the LLM call fails), stores it at `medical_reports/{patient_id}/{report_id}.pdf` and embeds a QR code for `{CLAIM_BASE_URL}?token=…`. The token is HS256-signed with `REPORT_TOKEN_SECRET`, carries `sub`, `scan_ids`, `iat`, `exp` (1 hour) and `purpose: report_claim`.

`POST /scans/claim` then:

1. rejects invalid, expired or wrong-purpose tokens (403);
2. finds the report whose `scan_ids` set equals the token's set exactly, returning a signed URL (404 if none);
3. grants nothing to the patient themselves or to a caller without a doctor profile;
4. for a doctor: extends an active relationship to 7 days, activates a pending one, or inserts a new `active` row (`note = 'QR claim'`);
5. refuses a token issued before a revoked or declined relationship ended, leaving the row unchanged;
6. returns **409** when two claims race; the partial unique index `care_rel_one_live` allows only one live row.

## Edge sync

`POST /sync/edge-inference` accepts a result computed on the phone with a client-generated `scan_id`. The image is uploaded and verified **before** the row is written (`inference_source='edge'`, `xai_status='skipped_edge'`), and the insert is `ON CONFLICT (scan_id) DO NOTHING`.

| Response | Meaning | Client action |
|---|---|---|
| 200 `synced` + `storage_path` | stored for the first time | delete the local copy |
| 409 `already_synced` + `storage_path` | retry of a stored scan | delete the local copy |
| 422 `scan_id_conflict`, 413, other 422 | permanent payload error | keep the file, stop, show the user |
| 503 / other 5xx | nothing persisted | keep the file, retry with back-off |

The client deletes its copy only when the response carries a non-null `storage_path`.

## Storage

Two private buckets:

```
scan-images      {user_id}/{scan_id}{ext}              original image
                 {user_id}/{scan_id}/overlay_{n}.png   explainability overlay
medical_reports  {patient_id}/{report_id}.pdf          generated report
```

Overlays are returned as authenticated URLs (`/storage/v1/object/authenticated/scan-images/{path}`) that require the caller's own token; reports use signed URLs that expire after 15 minutes. If a database insert fails after an upload, the uploaded objects are deleted.

## Configuration

Copy `.env.example` to `.env`. Required: `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_PUBLISHABLE_KEY`, `DATABASE_URL`, `REPORT_TOKEN_SECRET`, the four `*_SERVICE_URL` values. Optional: `GEMINI_API_KEY`, `GOOGLE_MODEL`, `CLAIM_BASE_URL`, `ANDROID_CERT_FINGERPRINTS`, `SUPABASE_STORAGE_BUCKET`, `MAX_UPLOAD_BYTES`, `ALLOWED_ORIGINS`, `DEV_MODE`, `DEV_TOKEN_SECRET`. See [`../README.md`](../README.md) for the full table.

## Run and test

```bash
uv sync --all-extras
uv run uvicorn app.main:app --app-dir src --reload --port 8000
curl http://localhost:8000/api/v1/health/healthz

uv run pytest -q                      # 329 passed
```

Docker: `docker build -t mediscanx-gateway . && docker run --env-file .env -p 8000:8000 mediscanx-gateway`.

## Errors

All errors share one envelope, `{"error": true, "type", "message", "context"}`. Status codes used on purpose: 401 (no or invalid token), 403 (authenticated but not allowed), 404, 409 (concurrent claim or duplicate sync), 413 (file too large), 422 (invalid input), 500 (unknown model label), 502/503 (a downstream service or storage is unavailable).
