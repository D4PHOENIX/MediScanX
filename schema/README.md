# Database Schema

The MediScanX database, defined in one file.

```
schema/
└── 0001_baseline.sql   complete schema definition
```

Applying `0001_baseline.sql` to an empty Supabase project produces the entire
database: tables, constraints, indexes, functions, triggers, row-level security,
storage buckets and their policies, and the PowerSync publication.

---

## Applying it

Requires a Supabase project. The script depends on `auth.users` and the
`storage` schema, neither of which exists in plain PostgreSQL.

```bash
psql "$DATABASE_URL" -f schema/0001_baseline_schema.sql
```

Or paste it into the Supabase SQL editor.

Safe to re-run. Every object uses `IF NOT EXISTS`, `OR REPLACE`, or a guarded
`DO` block, so applying it to a populated database makes no changes.

Sections must run in the order given — extensions before the typed columns that
depend on them, tables before their foreign keys, functions before the policies
that call them.

---

## What it contains

|                 |                                                              |
| --------------- | ------------------------------------------------------------ |
| **Tables**      | 11                                                           |
| **Policies**    | 15 row-level security policies across `public` and `storage` |
| **Functions**   | 8                                                            |
| **Triggers**    | 2                                                            |
| **Buckets**     | 2, both private                                              |
| **Publication** | `powersync`, over 5 tables                                   |

### Tables

| Table                                                                           | Purpose                                                                    |
| ------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `patient_records`                                                               | Patient profile, keyed on `auth.users(id)`                                 |
| `doctor_profiles`                                                               | Clinician profile — **membership here is the definition of "is a doctor"** |
| `care_relationships`                                                            | Consent records granting a doctor access to a patient                      |
| `scan_results`                                                                  | One row per diagnostic scan, across all three modalities                   |
| `reports`                                                                       | One row per generated PDF report                                           |
| `chat_messages`                                                                 | Conversational history with the medical assistant                          |
| `rag_corpus`                                                                    | Medical literature backing retrieval-augmented generation                  |
| `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations` | LangGraph agent state — structure defined by the library, do not alter     |

---

## Design decisions worth knowing

**Consent is a row, not a flag.** A doctor's access to a patient's data comes
from a `care_relationships` row with `status = 'active'` and an unexpired
`expires_at` — nothing else. There is no role column, no admin override, no
global doctor privilege. Every doctor-facing policy resolves through
`has_care_access()`, so the rule lives in exactly one place.

**`has_care_access()` takes one argument.** The doctor is resolved internally
from `auth.uid()`, so a caller cannot ask about a relationship that is not
their own. A two-argument call will fail.

**The service role bypasses RLS.** These policies govern the `authenticated`
role — clients reaching Postgres directly through PostgREST or PowerSync.
Backend writes are not constrained by them, which is why `reports` and
`care_relationships` have no client-facing write policies: adding one would
grant nothing the application needs while allowing a client to forge rows.

**Enumerations are enforced by CHECK constraints,** not by convention. Reading
the constraint gives the complete legal vocabulary without searching the
codebase:

| Column                          | Values                                           |
| ------------------------------- | ------------------------------------------------ |
| `scan_results.modality`         | `cxr` · `ecg` · `skin`                           |
| `scan_results.inference_source` | `cloud` · `edge`                                 |
| `scan_results.xai_status`       | `none` · `generated` · `skipped_edge` · `failed` |
| `care_relationships.status`     | `pending` · `active` · `declined` · `revoked`    |

**Absence is distinguished from failure.** `xai_status` is the clearest case:
`none`, `skipped_edge` and `failed` describe three different reasons an
explainability overlay is missing, so a client can present each honestly rather
than collapsing them into one null.

**`scan_status` derives from the finding, not from confidence alone.** Severity
is `0` Normal, `1` Warning, `2` High Risk. A model that is 99% certain a result
is normal must not read as high risk, so confidence thresholds apply only when
the diagnosis is an abnormal label for its modality.

**Storage paths carry authorisation.** Both buckets key their first path
segment to the owning patient's UUID, which lets a storage policy determine
ownership from the object name alone:

```
scan-images/
  {patient_id}/{scan_id}.{ext}            source image
  {patient_id}/{scan_id}/overlay_N.png    explainability overlay

medical_reports/
  {patient_id}/{report_id}.pdf            generated report
```

**Storage objects cannot be deleted with SQL.** A trigger on `storage.objects`
blocks direct `DELETE`, because removing the row would orphan the underlying
file. Deletion goes through the Storage API.

**Clinical artifacts are immutable.** Regenerating a report produces a new row
and a new object rather than replacing an existing one, so a report already
handed to a clinician does not change afterwards. `reports` has no foreign keys
for the same reason — it must remain retrievable even if a referenced scan is
later removed.

---

## Changing the schema

Add a new numbered file — `0002_*.sql`, and so on. Do not edit
`0001_baseline.sql`; it describes the schema as shipped, and editing it means
no environment can be reproduced from the repository.

Anything that must hold unconditionally belongs in a CHECK constraint or a
`SECURITY DEFINER` function rather than in application code. Five tables are
published to PowerSync, so clients write to them directly through the sync path
and application code is not the only route to the data.

---

## Verifying an applied schema

```sql
SELECT
  (SELECT count(*) FROM information_schema.tables
     WHERE table_schema='public' AND table_type='BASE TABLE')          AS tables,
  (SELECT count(*) FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid
     JOIN pg_namespace n ON n.oid=c.relnamespace
     WHERE n.nspname IN ('public','storage'))                          AS policies,
  (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
     WHERE n.nspname='public')                                         AS functions,
  (SELECT count(*) FROM storage.buckets)                               AS buckets;
```

Expected: **11 tables · 15 policies · 8 functions · 2 buckets**.

Confirm row-level security is enabled everywhere:

```sql
SELECT relname, relrowsecurity FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r'
ORDER BY relname;
```

Every row should read `true`.
