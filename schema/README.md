# schema

The MediScanX database, defined in one file.

```
schema/
├── mediscanx_schema.sql   complete, idempotent definition of the production database
└── README.md
```

Applying `mediscanx_schema.sql` to an empty Supabase project rebuilds the whole database as it runs in production. That covers extensions, tables, constraints, indexes, functions, triggers, row-level security, storage buckets and policies, the PowerSync and Realtime publications, and the scheduled consent-expiry job.

It replaces the former `0001_baseline_schema.sql` (migrations through 0112) and the follow-up migrations `0113`–`0117`. Their history stays in git.

## Applying it

The script needs a **Supabase** project, because it depends on `auth.users`, `auth.uid()`, the `storage` schema and the `pg_cron` extension package. It is not a plain PostgreSQL script.

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f schema/mediscanx_schema.sql
```

You can also paste it into the Supabase SQL editor. Use the direct connection or the session pooler; the transaction pooler cannot run `CREATE EXTENSION`.

It is safe to re-run. Every object uses `IF NOT EXISTS`, `CREATE OR REPLACE`, a `DROP … IF EXISTS` / `CREATE` pair or a guarded `DO` block. Applying it to a populated database leaves the data and the object set unchanged.

After applying, enable the PowerSync sync rules for the `powersync` publication in the PowerSync dashboard. The backend needs nothing else; the gateway's start-up migration guard checks that `scan_results.inference_source` and `storage_path` exist.

## Sections

| # | Section | Contents |
|---|---|---|
| 1 | Extensions | `uuid-ossp`, `pgcrypto`, `vector` (vector + halfvec), `pg_stat_statements` in `extensions`; `pg_cron` |
| 2 | Identity | `patient_records`, `doctor_profiles`, both keyed on `auth.users(id)` |
| 3 | Consent | `care_relationships`, the one-live-row partial unique index, the `expires_at` contract |
| 4 | Diagnostic results | `scan_results` with modality / source / XAI CHECK constraints and indexes |
| 5 | Reports | `reports` |
| 6 | Agent | `chat_messages` and the four LangGraph `checkpoint*` tables |
| 7 | Retrieval corpus | `rag_corpus` (halfvec(768), HNSW cosine index) |
| 8 | Functions | consent check and RPCs, profile trigger function, RAG search, maintenance |
| 9 | Triggers | `on_auth_user_created` on `auth.users`, `updated_at` on `scan_results` |
| 10 | Row-level security | RLS on every table, 15 policies |
| 11 | Storage | `scan-images` and `medical_reports` buckets (private, 25 MB), 4 object policies |
| 12 | Publications | `powersync` (5 tables); `doctor_profiles` and `patient_records` added to `supabase_realtime` when it exists |
| 13 | Scheduled jobs | `expire-care-relationships`, every 5 minutes |

## What it contains

| | |
|---|---|
| Tables | 11, all with RLS enabled |
| Policies | 15 on `public` tables + 4 on `storage.objects` |
| Indexes | 30 |
| Functions | 10 |
| Triggers | 2 |
| Buckets | 2, both private |
| Cron jobs | 1 |

### Tables

| Table | Purpose |
|---|---|
| `patient_records` | Patient profile, keyed on `auth.users(id)` |
| `doctor_profiles` | Doctor profile. **A row here is what makes a user a doctor** |
| `care_relationships` | Consent: a doctor's access to one patient (`pending` · `active` · `declined` · `revoked`) |
| `scan_results` | One row per scan across all three modalities, cloud or edge |
| `reports` | One row per generated PDF referral report |
| `chat_messages` | Assistant conversation history shown in the app (replicated by PowerSync) |
| `rag_corpus` | 768-dim MedCPT embeddings of the retrieval corpus |
| `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations` | LangGraph agent state; structure owned by the library. Don't alter it |

### Functions

| Function | Role |
|---|---|
| `has_care_access(p_patient)` | The single consent check behind every doctor-facing policy. Resolves the doctor from `auth.uid()` and requires an `active`, unexpired relationship |
| `request_care`, `respond_to_care`, `revoke_care` | Consent RPCs. A doctor requests, the patient accepts or declines, either side revokes |
| `list_care_relationships()` | The calling patient's pending and active relationships, with the doctor's name, specialty and hospital, for the app's consent screen |
| `expire_care_relationships()` | Marks relationships past `expires_at` as revoked. Executable only by `service_role`; run by cron |
| `handle_new_user_profile()` | Creates the patient or doctor profile from sign-up metadata (trigger on `auth.users`) |
| `update_updated_at_column()` | `updated_at` trigger function |
| `match_rag_corpus(...)` | Cosine similarity search over `rag_corpus`, filterable by source and specialty |
| `find_orphaned_scan_objects(p_min_age)` | Storage objects in `scan-images` with no matching scan row, for clean-up |

## Design decisions

**Consent is a row, not a flag.** A doctor's access to a patient comes only from a `care_relationships` row with `status = 'active'` and no past `expires_at`. There is no role column, admin override or global doctor privilege. Every doctor-facing policy, in tables and storage alike, goes through `has_care_access()`, so the rule lives in one place.

**Expiry has two paths.** A QR claim (`POST /api/v1/scans/claim`) creates or extends a relationship for 7 days. The `request_care` / `respond_to_care` RPCs leave `expires_at` NULL, which means it lasts until revoked. `has_care_access()` refuses expired rows immediately. The cron sweep then marks them `revoked`, with `ended_at` set, so the PowerSync doctor bucket, which is scoped on `status = 'active'`, drops the patient's rows from the doctor's device. A non-null `expires_at` tells an expiry apart from a manual revoke.

**One live relationship per pair.** The partial unique index `care_rel_one_live` on `(patient_id, doctor_id) WHERE status IN ('pending','active')` makes concurrent QR claims collide. The gateway turns that collision into a 409 instead of creating duplicates.

**The service role bypasses RLS.** The policies govern the `authenticated` role, meaning clients going through PostgREST, Storage or PowerSync. The checkpoint tables have RLS on and no policies, so only the backend can read them.

**Enumerations are CHECK constraints,** so the constraint is the full legal vocabulary:

| Column | Values |
|---|---|
| `scan_results.modality` | `cxr` · `ecg` · `skin` |
| `scan_results.inference_source` | `cloud` · `edge` |
| `scan_results.xai_status` | `none` · `generated` · `skipped_edge` · `failed` |
| `care_relationships.status` | `pending` · `active` · `declined` · `revoked` |

**`scan_status` comes from the finding first.** `0` Normal, `1` Warning, `2` High Risk. A confidently normal result can never read as high risk, because the confidence threshold applies only to abnormal labels. The gateway derives it; see `backend/gateway_backend/README.md`.

**Storage paths carry authorisation.** The first path segment is the owning patient's UUID, so a storage policy can decide ownership from the object name alone:

```
scan-images/       {patient_id}/{scan_id}{ext}              source image
                   {patient_id}/{scan_id}/overlay_{n}.png   explainability overlay
medical_reports/   {patient_id}/{report_id}.pdf             generated report
```

A doctor can also read the images of scans they captured themselves (`scan_results.doctor_id`). Users can upload to and delete from only their own `scan-images` folder.

## Verifying an applied schema

```sql
SELECT
  (SELECT count(*) FROM pg_tables   WHERE schemaname = 'public')                    AS tables,
  (SELECT count(*) FROM pg_policies WHERE schemaname = 'public')                    AS public_policies,
  (SELECT count(*) FROM pg_policies WHERE schemaname = 'storage'
                                      AND policyname IN ('scan_images_read','scan_images_write',
                                                         'scan_images_delete','medical_reports_read')) AS storage_policies,
  (SELECT count(*) FROM pg_indexes  WHERE schemaname = 'public')                    AS indexes,
  (SELECT count(*) FROM pg_proc     WHERE pronamespace = 'public'::regnamespace)    AS functions,
  (SELECT count(*) FROM storage.buckets
     WHERE id IN ('scan-images','medical_reports'))                                 AS buckets,
  (SELECT count(*) FROM cron.job    WHERE jobname = 'expire-care-relationships')    AS cron_jobs;
```

Expected result on a fresh project: **11 · 15 · 4 · 30 · 10 · 2 · 1**. Every `relrowsecurity` should be `true`:

```sql
SELECT relname, relrowsecurity FROM pg_class
WHERE relnamespace = 'public'::regnamespace AND relkind = 'r' ORDER BY relname;
```

The file was checked against the live project in October 2026. It was applied twice to a clean PostgreSQL 16 instance with pg_cron, pgvector 0.8 and Supabase `auth` / `storage` stand-ins. I then compared columns, constraints, indexes, policies, function bodies (hashed), triggers, RLS flags, buckets, the cron job and grants with the live catalog. All of them match. The live database has one extra function, the unused legacy `handle_new_user()`, which references columns that no longer exist and is deliberately not recreated, so a live project reports 11 functions.

## Changing the schema

Edit `mediscanx_schema.sql` in place and keep it idempotent and in section order. Apply the same change to the live project in the same pull request, and say in the PR how you verified that the two still match. Anything that must always hold belongs in a CHECK constraint, a policy or a `SECURITY DEFINER` function rather than in application code. The five PowerSync tables are written by clients directly, so the backend is not the only way into that data.
