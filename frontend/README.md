# frontend

The MediScanX Android app, built in Flutter. It captures a chest X-ray, a photo of an ECG printout or a skin lesion with the phone camera. It analyses the image in the cloud, or on the device when there is no connection, and shows the explainability overlay. It also tracks results over time, fuses modalities, hosts the clinical assistant chat, and shares a QR-claimable referral report with a doctor.

Flutter · Dart ≥ 3.0 · Riverpod · go_router · Supabase · PowerSync · Drift · tflite_flutter

## Stack

| Package | Used for |
|---|---|
| `flutter_riverpod`, `riverpod_generator` | state management |
| `go_router`, `app_links` | navigation and Android App Links (`/claim?token=…`) |
| `supabase_flutter` | sign-up, login, JWT session, authenticated Storage reads |
| `powersync`, `drift`, `drift_sqlite_async` | local SQLite database replicated from Postgres (offline-first) |
| `tflite_flutter`, `image` | on-device chest X-ray and skin inference |
| `http`, `dio`, `flutter_client_sse` | gateway API calls and the streamed assistant chat |
| `fl_chart`, `flutter_markdown`, `qr_flutter` | trend charts, chat rendering, report QR codes |
| `connectivity_plus` | network detection that triggers the offline outbox |

## Layout

```
lib/
├── main.dart                 app start-up, dotenv, Supabase + PowerSync init, router
├── core/
│   ├── config/               env_config (reads .env), Drift database
│   ├── database/             PowerSync schema, Supabase connector, database manager
│   ├── ml/                   cxr_tflite_engine, skin_tflite_engine
│   ├── network/              API client
│   └── themes, utils, widgets
├── features/
│   ├── auth/                 login, registration (patient or doctor), password reset
│   ├── dashboard/            home, temporal selection and trend charts
│   ├── diagnostic/           capture, cloud / edge inference, results, fusion, edge outbox
│   ├── chat/                 assistant chat (SSE) and chat history
│   ├── referral/             report generation, care relationships
│   ├── triage/               doctor's triage queue and QR claim
│   ├── downloads/            saved reports
│   └── debug/                profile-sync debug screen
├── config/                   app routes
└── shared/                   shared models, services and widgets

```

## Prerequisites

- Flutter SDK (Dart ≥ 3.0) and the Android SDK; `minSdk 24`, `compileSdk 36`
- A running MediScanX backend and Supabase project (see the [root README](../README.md))

## Setup

```bash
cd frontend
cp .env.example .env
flutter pub get
dart run build_runner build --delete-conflicting-outputs   # generates *.g.dart / *.freezed.dart
```

`.env` is bundled as an asset (`pubspec.yaml`), so the build fails if the file is missing. It is gitignored and must never be committed.

| Variable | Value |
|---|---|
| `SUPABASE_URL` | `https://<project-ref>.supabase.co` |
| `SUPABASE_ANON_KEY` | the project's publishable key |
| `POWERSYNC_URL` | the PowerSync instance URL |
| `API_BASE_URL` | the gateway **including** `/api/v1`, e.g. `https://mediscanx.app/api/v1` |

The app builds every request as `${API_BASE_URL}/cxr/predict`, `/scans/claim` and so on, so the value must end in `/api/v1`. An empty value falls back to a placeholder host, and nothing will work.

## On-device models

| File | Model | Input | Notes |
|---|---|---|---|
| `assets/models/cxr_model/cxr_model.tflite` | DenseNet-121 + SE (CIHMLC), TFLite INT8 | 320 × 320 | ~194 ms on CPU; no overlay |
| `assets/models/skin_model/skin_multidomain_fp32.tflite` | EfficientNet-B0, LiteRT FP32, 8 classes | 224 × 224 | ~31 ms on CPU; bit-exact parity with PyTorch |

No ECG model ships to the device, so ECG analysis needs a connection. Preprocessing in the engines mirrors the server pipelines (see `backend/cxr_service` and `backend/skin_service`).

## Offline behaviour

- PowerSync keeps `patient_records`, `doctor_profiles`, `scan_results` and `chat_messages` in a local SQLite database, so history and chat stay readable offline.
- Without a network, a chest X-ray or skin scan runs on the device. The result is written to the local `pending_sync_scans` outbox with the image path, the findings and a retry count.
- `EdgeOutboxService` drains the outbox to `POST /api/v1/sync/edge-inference` when the connection returns. It deletes the local copy only when the response carries a non-null `storage_path` (200 `synced` or 409 `already_synced`). It keeps the file and stops on a permanent 4xx, and retries with back-off on 5xx.

## Main routes

`/login`, `/register`, `/dashboard`, `/diagnostic`, `/skin-diagnostic`, `/diagnostic-result/:module`, `/temporal-tracking/:modality`, `/fusion-result`, `/ai-chat`, `/chat-history`, `/referral-package`, `/care-relationships`, `/triage` (doctors), `/downloads`, `/claim` (App Link target), `/sync-debug`.

## Run, test and build

```bash
flutter run                                   # debug on a connected device
flutter analyze
flutter test                                  # widget test for the sync debug screen
flutter build apk --release --split-per-abi   # APKs in build/app/outputs/flutter-apk/
```

Release builds are published on the [Releases page](https://github.com/D4PHOENIX/MediScanX/releases); `MediScanX-v1.0.0-arm64-v8a.apk` covers almost all current phones.