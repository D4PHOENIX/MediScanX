# Frontend (Flutter client)

The `frontend/` directory contains the Flutter client used by MediScanX. The primary app entrypoint is `lib/main.dart` and on-device models and assets live under `assets/` (and `mobile_app/assets/` for the mobile-targeted app).

## Environment

Create a local `.env` from the example and populate the required values:

```bash
cp .env.example .env
# set SUPABASE_URL, SUPABASE_ANON_KEY, POWERSYNC_URL, API_BASE_URL
```

`.env` is gitignored and must not be committed.

## Local development

Install dependencies and run on a connected device or emulator:

```bash
flutter pub get
flutter run -d <device-id>
```

To build a release APK (Android):

```bash
flutter build apk --release
```

Notes:

- Place any on-device model files (TFLite) in the assets folder expected by the app (see `assets/models/`).
- The app expects the backend gateway at `API_BASE_URL` (set via environment).
