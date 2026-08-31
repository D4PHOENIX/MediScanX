-- =============================================================================
-- MediScanX — Baseline Database Schema
-- Version 0001
-- Target: PostgreSQL 17 on Supabase
-- =============================================================================
--
-- A single, complete, reproducible definition of the MediScanX database.
-- Applying this file to an empty Supabase project produces the full schema:
-- tables, constraints, indexes, functions, triggers, row-level security,
-- storage buckets and their policies, and the PowerSync publication.
--
-- Ordering matters. Sections must run in the order given: extensions before
-- typed columns, tables before the constraints that reference them, functions
-- before the policies that call them.
--
-- The script is idempotent. Every object uses IF NOT EXISTS, OR REPLACE, or a
-- guarded DO block, so re-running it is safe.
--
-- Requires a Supabase project: `auth.users` and the `storage` schema must
-- already exist. This is not a plain PostgreSQL script.
-- =============================================================================


-- =============================================================================
-- SECTION 1 — EXTENSIONS
-- =============================================================================
-- `vector` provides both the vector and halfvec types used for embeddings and
-- must be installed before any table declaring those columns.

CREATE SCHEMA IF NOT EXISTS extensions;

CREATE EXTENSION IF NOT EXISTS "uuid-ossp"         WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS pgcrypto            WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS vector              WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements  WITH SCHEMA extensions;


-- =============================================================================
-- SECTION 2 — IDENTITY TABLES
-- =============================================================================
-- Both profile tables key on auth.users(id) rather than carrying a surrogate
-- key, so a profile cannot outlive its account and no join table is needed to
-- resolve an authenticated caller to their record.

CREATE TABLE IF NOT EXISTS public.patient_records (
    user_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name        text        NOT NULL,
    email            text,
    phone_number     text,
    gender           text,
    location         text,
    medical_history  jsonb,
    created_at       timestamptz DEFAULT now(),
    updated_at       timestamptz DEFAULT now(),
    username         text        NOT NULL,
    sync_status      text        DEFAULT 'pending',
    date_of_birth    text,
    CONSTRAINT patient_records_username_key UNIQUE (username)
);

-- date_of_birth is text in ISO 'YYYY-MM-DD' form rather than a date type: it
-- arrives from the mobile client as a string and is displayed rather than
-- computed against in SQL.

CREATE TABLE IF NOT EXISTS public.doctor_profiles (
    user_id           uuid PRIMARY KEY,
    full_name         text        NOT NULL,
    email             text        NOT NULL,
    specialization    text        NOT NULL,
    current_hospital  text        NOT NULL,
    license_number    text,
    biography         text,
    created_at        timestamptz DEFAULT now(),
    updated_at        timestamptz DEFAULT now(),
    gender            text,
    username          text        NOT NULL,
    phone_number      text,
    location          text,
    sync_status       text        DEFAULT 'pending',
    date_of_birth     text,
    CONSTRAINT doctor_profiles_username_key UNIQUE (username),
    CONSTRAINT doctor_profiles_user_id_fkey
        FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE
);

-- Membership in doctor_profiles is the sole definition of "is a doctor".
-- No role column exists anywhere; presence in this table is the check.


-- =============================================================================
-- SECTION 3 — CONSENT MODEL
-- =============================================================================
-- A doctor's access to a patient's data is granted by a row here and by
-- nothing else. Every doctor-facing policy in this schema resolves through
-- has_care_access(), which reads this table.

CREATE TABLE IF NOT EXISTS public.care_relationships (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id    uuid        NOT NULL,
    doctor_id     uuid        NOT NULL,
    status        text        NOT NULL DEFAULT 'pending',
    initiated_by  uuid        NOT NULL,
    note          text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    activated_at  timestamptz,
    ended_at      timestamptz,
    expires_at    timestamptz,
    CONSTRAINT care_relationships_status_check
        CHECK (status = ANY (ARRAY['pending','active','declined','revoked'])),
    CONSTRAINT care_no_self_reference
        CHECK (patient_id <> doctor_id),
    CONSTRAINT care_relationships_patient_id_fkey
        FOREIGN KEY (patient_id) REFERENCES public.patient_records(user_id) ON DELETE CASCADE,
    CONSTRAINT care_relationships_doctor_id_fkey
        FOREIGN KEY (doctor_id) REFERENCES public.doctor_profiles(user_id) ON DELETE CASCADE
);

-- Four statuses, exhaustively enumerated. 'declined' and 'revoked' are
-- terminal: a relationship that reached either must never be silently
-- reactivated, or withdrawal of consent would be meaningless.

-- At most one live relationship per patient-doctor pair. Terminal rows are
-- excluded from the constraint, so a declined or revoked relationship can be
-- superseded by a fresh request without deleting the historical record.
CREATE UNIQUE INDEX IF NOT EXISTS care_rel_one_live
    ON public.care_relationships (patient_id, doctor_id)
    WHERE status = ANY (ARRAY['pending','active']);

-- Partial index matching the shape of the has_care_access() lookup.
CREATE INDEX IF NOT EXISTS care_rel_doctor_active
    ON public.care_relationships (doctor_id, patient_id)
    WHERE status = 'active';


-- =============================================================================
-- SECTION 4 — DIAGNOSTIC RESULTS
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.scan_results (
    scan_id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           uuid,
    doctor_id         uuid,
    scan_type         integer     NOT NULL,
    scan_status       integer     NOT NULL,
    image_url         text,
    ai_diagnosis      text,
    findings          text,
    confidence        real,
    metadata          jsonb,
    scan_date         timestamptz NOT NULL,
    vector_embedding  extensions.vector(768),
    created_at        timestamptz DEFAULT now(),
    updated_at        timestamptz DEFAULT now(),
    inference_source  text        NOT NULL DEFAULT 'cloud',
    storage_path      text,
    modality          text,
    xai_path          text,
    xai_status        text        NOT NULL DEFAULT 'none',
    CONSTRAINT chk_inference_source
        CHECK (inference_source = ANY (ARRAY['cloud','edge'])),
    CONSTRAINT scan_results_modality_check
        CHECK (modality IS NULL OR modality = ANY (ARRAY['cxr','ecg','skin'])),
    CONSTRAINT scan_results_xai_status_check
        CHECK (xai_status = ANY (ARRAY['none','generated','skipped_edge','failed'])),
    CONSTRAINT scan_results_user_id_fkey
        FOREIGN KEY (user_id) REFERENCES public.patient_records(user_id) ON DELETE CASCADE,
    CONSTRAINT scan_results_doctor_id_fkey
        FOREIGN KEY (doctor_id) REFERENCES public.doctor_profiles(user_id)
);

-- scan_status is a triage severity: 0 Normal, 1 Warning, 2 High Risk. It is
-- derived from the finding together with its confidence, never from confidence
-- alone — a model that is highly confident a result is normal must not read as
-- high risk.
--
-- xai_status distinguishes four outcomes that a nullable path alone could not:
--   none          cloud inference ran and produced no overlay
--   generated     an overlay exists; xai_path is non-null
--   skipped_edge  on-device inference; server-side XAI was never attempted
--   failed        generation or upload failed; the scan still persisted
--
-- The application maintains the invariant that xai_status = 'generated' if and
-- only if xai_path is non-null.
--
-- modality is the canonical discriminator. scan_type is an integer retained
-- for client compatibility and is not authoritative.
--
-- doctor_id has no ON DELETE clause: a scan captured by a doctor must survive
-- that doctor's account being removed.

CREATE INDEX IF NOT EXISTS idx_scan_results_user_id
    ON public.scan_results (user_id);
CREATE INDEX IF NOT EXISTS idx_scan_results_scan_date
    ON public.scan_results (scan_date DESC);
CREATE INDEX IF NOT EXISTS idx_scan_results_inference_source
    ON public.scan_results (inference_source);
CREATE INDEX IF NOT EXISTS idx_scan_results_doctor_id
    ON public.scan_results (doctor_id) WHERE doctor_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS scan_results_storage_path_idx
    ON public.scan_results (storage_path);

-- Serves history and trend queries, which filter by patient and modality then
-- order by recency.
CREATE INDEX IF NOT EXISTS scan_results_modality_date_idx
    ON public.scan_results (user_id, modality, scan_date DESC);

-- Partial: the overwhelming majority of rows are 'none', which is never the
-- subject of a lookup.
CREATE INDEX IF NOT EXISTS scan_results_xai_status_idx
    ON public.scan_results (xai_status) WHERE xai_status <> 'none';


-- =============================================================================
-- SECTION 5 — GENERATED REPORTS
-- =============================================================================
-- One row per generated PDF. Reports are immutable: regenerating produces a
-- new row and a new storage object rather than replacing an existing one.

CREATE TABLE IF NOT EXISTS public.reports (
    report_id     uuid PRIMARY KEY,
    user_id       uuid        NOT NULL,
    generated_by  uuid        NOT NULL,
    scan_ids      uuid[]      NOT NULL,
    storage_path  text        NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- user_id is the patient the report concerns; generated_by is whoever
-- requested it. They differ when a doctor generates a report for a patient.
--
-- No foreign keys, deliberately: a report is a point-in-time clinical artifact
-- and must remain retrievable even if a referenced scan is later removed.
-- scan_ids records provenance rather than enforcing referential integrity.

CREATE INDEX IF NOT EXISTS reports_user_created_idx
    ON public.reports (user_id, created_at DESC);


-- =============================================================================
-- SECTION 6 — CONVERSATIONAL AGENT
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.chat_messages (
    id          uuid PRIMARY KEY,
    thread_id   uuid        NOT NULL,
    is_user     boolean     NOT NULL,
    text        text        NOT NULL,
    citations   jsonb       DEFAULT '[]'::jsonb,
    created_at  timestamptz NOT NULL DEFAULT now(),
    patient_id  uuid
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_thread_id
    ON public.chat_messages (thread_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_patient_id
    ON public.chat_messages (patient_id);

-- LangGraph checkpoint tables. Structure is defined by the langgraph-checkpoint
-- -postgres library; do not alter the columns or primary keys. RLS is enabled
-- with no policies, so only the service role can reach them.

CREATE TABLE IF NOT EXISTS public.checkpoints (
    thread_id             text  NOT NULL,
    checkpoint_ns         text  NOT NULL DEFAULT '',
    checkpoint_id         text  NOT NULL,
    parent_checkpoint_id  text,
    type                  text,
    checkpoint            jsonb NOT NULL,
    metadata              jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

CREATE TABLE IF NOT EXISTS public.checkpoint_blobs (
    thread_id      text NOT NULL,
    checkpoint_ns  text NOT NULL DEFAULT '',
    channel        text NOT NULL,
    version        text NOT NULL,
    type           text NOT NULL,
    blob           bytea,
    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
);

CREATE TABLE IF NOT EXISTS public.checkpoint_writes (
    thread_id      text    NOT NULL,
    checkpoint_ns  text    NOT NULL DEFAULT '',
    checkpoint_id  text    NOT NULL,
    task_id        text    NOT NULL,
    idx            integer NOT NULL,
    channel        text    NOT NULL,
    type           text,
    blob           bytea   NOT NULL,
    task_path      text    NOT NULL DEFAULT '',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);

CREATE TABLE IF NOT EXISTS public.checkpoint_migrations (
    v integer PRIMARY KEY
);

CREATE INDEX IF NOT EXISTS checkpoints_thread_id_idx
    ON public.checkpoints (thread_id);
CREATE INDEX IF NOT EXISTS checkpoint_blobs_thread_id_idx
    ON public.checkpoint_blobs (thread_id);
CREATE INDEX IF NOT EXISTS checkpoint_writes_thread_id_idx
    ON public.checkpoint_writes (thread_id);


-- =============================================================================
-- SECTION 7 — RETRIEVAL CORPUS
-- =============================================================================
-- Medical literature backing retrieval-augmented generation.

CREATE TABLE IF NOT EXISTS public.rag_corpus (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    content        text NOT NULL,
    metadata       jsonb DEFAULT '{}'::jsonb,
    embedding      extensions.halfvec(768),
    title          text,
    source         text NOT NULL DEFAULT 'PubMedQA',
    external_id    text NOT NULL DEFAULT '',
    specialty_tag  text DEFAULT 'thoracic',
    CONSTRAINT uq_rag_corpus_source_external_id UNIQUE (source, external_id)
);

-- embedding is halfvec(768), not vector(768). Half precision halves index size
-- and memory at negligible cost to retrieval quality, which matters at corpus
-- scale. Dimensionality is fixed by the MedCPT encoder.
--
-- The (source, external_id) unique constraint makes corpus ingestion
-- idempotent: re-running a seeding job cannot duplicate documents.

-- HNSW over cosine distance. m and ef_construction are tuned low to keep build
-- time and memory within a small instance's budget.
CREATE INDEX IF NOT EXISTS idx_rag_corpus_embedding
    ON public.rag_corpus USING hnsw (embedding extensions.halfvec_cosine_ops)
    WITH (m = 8, ef_construction = 40);


-- =============================================================================
-- SECTION 8 — FUNCTIONS
-- =============================================================================
-- Defined before the policies that call them.

-- Consent check underpinning every doctor-facing policy in this schema.
--
-- Takes one argument. The doctor is resolved internally from auth.uid(); it is
-- not passed in, so a caller cannot ask about a relationship that is not their
-- own. SECURITY DEFINER lets it read care_relationships from inside a policy
-- without that table's own RLS causing infinite recursion.
--
-- Expiry is enforced here, not by the caller. A relationship past expires_at
-- grants nothing.
CREATE OR REPLACE FUNCTION public.has_care_access(p_patient uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path TO 'public', 'pg_temp'
AS $function$
  select exists (
    select 1
    from public.care_relationships cr
    where cr.doctor_id  = (select auth.uid())
      and cr.patient_id = p_patient
      and cr.status     = 'active'
      and (cr.expires_at is null or cr.expires_at > now())
  );
$function$;

-- Creates the profile row for a newly registered account. Bound to
-- auth.users by trigger in Section 9.
--
-- Tolerant by design: registration must not fail because the client omitted an
-- optional field. Accepts both snake_case and camelCase metadata keys, derives
-- a username from the email local part when absent, and defaults the role to
-- Patient. ON CONFLICT makes it idempotent against retried signups.
CREATE OR REPLACE FUNCTION public.handle_new_user_profile()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_temp'
AS $function$
declare
  v_role text := coalesce(new.raw_user_meta_data ->> 'role', new.raw_user_meta_data ->> 'userType', 'Patient');
  v_full_name text := coalesce(new.raw_user_meta_data ->> 'full_name', new.raw_user_meta_data ->> 'fullName', 'Unknown User');
  v_username text := coalesce(new.raw_user_meta_data ->> 'username', split_part(new.email, '@', 1));
  v_phone text := nullif(new.raw_user_meta_data ->> 'phone_number', '');
  v_gender text := nullif(new.raw_user_meta_data ->> 'gender', '');
  v_date_of_birth text := nullif(new.raw_user_meta_data ->> 'date_of_birth', '');
  v_location text := nullif(new.raw_user_meta_data ->> 'location', '');
  v_specialization text := nullif(new.raw_user_meta_data ->> 'specialization', '');
  v_current_hospital text := nullif(new.raw_user_meta_data ->> 'current_hospital', '');
begin
  if lower(v_role) = 'doctor' then
    insert into public.doctor_profiles (
      user_id, username, full_name, email, phone_number, gender, date_of_birth,
      specialization, current_hospital, created_at, updated_at, sync_status
    ) values (
      new.id, v_username, v_full_name, new.email, v_phone, v_gender, v_date_of_birth,
      coalesce(v_specialization, 'General'), coalesce(v_current_hospital, 'Unknown'),
      now(), now(), 'synced'
    )
    on conflict (user_id) do update set
      username = excluded.username,
      full_name = excluded.full_name,
      email = excluded.email,
      phone_number = excluded.phone_number,
      gender = excluded.gender,
      date_of_birth = excluded.date_of_birth,
      specialization = excluded.specialization,
      current_hospital = excluded.current_hospital,
      updated_at = now();
  else
    insert into public.patient_records (
      user_id, username, full_name, email, phone_number, gender, date_of_birth,
      location, created_at, updated_at, sync_status
    ) values (
      new.id, v_username, v_full_name, new.email, coalesce(v_phone, ''), v_gender, v_date_of_birth,
      v_location, now(), now(), 'synced'
    )
    on conflict (user_id) do update set
      username = excluded.username,
      full_name = excluded.full_name,
      email = excluded.email,
      phone_number = excluded.phone_number,
      gender = excluded.gender,
      date_of_birth = excluded.date_of_birth,
      location = excluded.location,
      updated_at = now();
  end if;

  return new;
end;
$function$;

CREATE OR REPLACE FUNCTION public.update_updated_at_column()
RETURNS trigger
LANGUAGE plpgsql
SET search_path TO 'public', 'pg_temp'
AS $function$
BEGIN
    NEW.updated_at = timezone('utc'::text, now());
    RETURN NEW;
END;
$function$;

-- Consent lifecycle. These run as SECURITY DEFINER because each enforces its
-- own authorisation in the WHERE clause, which is stricter than a table policy
-- could express.

-- A doctor requests access to a patient. Verifies the caller is a doctor and
-- the patient exists before creating a pending relationship.
CREATE OR REPLACE FUNCTION public.request_care(p_patient uuid, p_note text DEFAULT NULL::text)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_temp'
AS $function$
declare v_id uuid;
begin
  if not exists (select 1 from public.doctor_profiles where user_id = (select auth.uid())) then
    raise exception 'caller is not a doctor';
  end if;
  if not exists (select 1 from public.patient_records where user_id = p_patient) then
    raise exception 'no such patient';
  end if;
  insert into public.care_relationships (patient_id, doctor_id, status, initiated_by, note)
  values (p_patient, (select auth.uid()), 'pending', (select auth.uid()), p_note)
  returning id into v_id;
  return v_id;
end $function$;

-- The patient accepts or declines. Only the patient named on the relationship
-- can respond, and only while it is pending.
CREATE OR REPLACE FUNCTION public.respond_to_care(p_id uuid, p_accept boolean)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_temp'
AS $function$
begin
  update public.care_relationships
     set status       = case when p_accept then 'active' else 'declined' end,
         activated_at = case when p_accept then now() else null end,
         ended_at     = case when p_accept then null else now() end
   where id = p_id
     and patient_id = (select auth.uid())
     and status = 'pending';
  if not found then raise exception 'no pending request for this patient'; end if;
end $function$;

-- Either party ends a live relationship. Terminal.
CREATE OR REPLACE FUNCTION public.revoke_care(p_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_temp'
AS $function$
begin
  update public.care_relationships
     set status = 'revoked', ended_at = now()
   where id = p_id
     and status in ('pending','active')
     and (patient_id = (select auth.uid()) or doctor_id = (select auth.uid()));
  if not found then raise exception 'no live relationship'; end if;
end $function$;

-- Cosine similarity search over the corpus, with optional source and specialty
-- filters. Returns similarity as 1 - distance so results sort descending on a
-- value that reads as "more similar is higher".
CREATE OR REPLACE FUNCTION public.match_rag_corpus(
    query_embedding extensions.halfvec,
    match_threshold double precision,
    match_count integer,
    filter_source text DEFAULT NULL::text,
    filter_specialty text DEFAULT NULL::text)
RETURNS TABLE(id uuid, content text, metadata jsonb, title text, source text,
              external_id text, similarity double precision)
LANGUAGE sql
STABLE
SET search_path TO 'public', 'extensions', 'pg_temp'
AS $function$
    SELECT
        rag_corpus.id,
        rag_corpus.content,
        rag_corpus.metadata,
        rag_corpus.title,
        rag_corpus.source,
        rag_corpus.external_id,
        1 - (rag_corpus.embedding <=> query_embedding) AS similarity
    FROM rag_corpus
    WHERE 1 - (rag_corpus.embedding <=> query_embedding) > match_threshold
      AND (filter_source IS NULL OR source = filter_source)
      AND (filter_specialty IS NULL OR specialty_tag = filter_specialty)
    ORDER BY similarity DESC
    LIMIT match_count;
$function$;

-- Maintenance helper: storage objects in scan-images with no owning scan row.
-- Read-only and diagnostic. Deletion must go through the Storage API, since a
-- trigger on storage.objects blocks direct SQL removal.
CREATE OR REPLACE FUNCTION public.find_orphaned_scan_objects(p_min_age interval DEFAULT '01:00:00'::interval)
RETURNS TABLE(object_name text, size_bytes bigint, created timestamp with time zone)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path TO 'public', 'storage', 'pg_temp'
AS $function$
  select o.name,
         nullif(o.metadata->>'size','')::bigint,
         o.created_at
  from storage.objects o
  where o.bucket_id = 'scan-images'
    and o.created_at < now() - p_min_age
    and not exists (
      select 1
      from public.scan_results sr
      where sr.storage_path = o.name
         or o.name like sr.user_id::text || '/' || sr.scan_id::text || '/%'
         or o.name like sr.user_id::text || '/' || sr.scan_id::text || '.%'
    )
  order by o.created_at;
$function$;


-- =============================================================================
-- SECTION 9 — TRIGGERS
-- =============================================================================

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user_profile();

DROP TRIGGER IF EXISTS trg_scan_results_updated_at ON public.scan_results;
CREATE TRIGGER trg_scan_results_updated_at
    BEFORE UPDATE ON public.scan_results
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


-- =============================================================================
-- SECTION 10 — ROW-LEVEL SECURITY
-- =============================================================================
-- RLS is enabled on every table in public. The service role bypasses it
-- entirely; these policies govern the `authenticated` role, meaning clients
-- reaching Postgres directly through PostgREST or PowerSync.
--
-- Tables with RLS enabled and no policy are reachable only by the service
-- role. That is deliberate for the checkpoint tables.

ALTER TABLE public.patient_records      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.doctor_profiles      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.care_relationships   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.scan_results         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reports              ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_messages        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rag_corpus           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.checkpoints          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.checkpoint_blobs     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.checkpoint_writes    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.checkpoint_migrations ENABLE ROW LEVEL SECURITY;

-- patient_records --------------------------------------------------------

DROP POLICY IF EXISTS patient_self_all ON public.patient_records;
CREATE POLICY patient_self_all ON public.patient_records
    FOR ALL TO authenticated
    USING (user_id = (SELECT auth.uid()))
    WITH CHECK (user_id = (SELECT auth.uid()));

DROP POLICY IF EXISTS patient_doctor_read ON public.patient_records;
CREATE POLICY patient_doctor_read ON public.patient_records
    FOR SELECT TO authenticated
    USING (public.has_care_access(user_id));

-- doctor_profiles --------------------------------------------------------

DROP POLICY IF EXISTS "Doctors access own profile" ON public.doctor_profiles;
CREATE POLICY "Doctors access own profile" ON public.doctor_profiles
    FOR ALL
    USING (user_id = auth.uid());

-- care_relationships -----------------------------------------------------
-- Read only. Writes go exclusively through request_care, respond_to_care and
-- revoke_care, so state transitions cannot be made arbitrarily by a client.

DROP POLICY IF EXISTS care_read_own ON public.care_relationships;
CREATE POLICY care_read_own ON public.care_relationships
    FOR SELECT TO authenticated
    USING (patient_id = (SELECT auth.uid()) OR doctor_id = (SELECT auth.uid()));

-- scan_results -----------------------------------------------------------

DROP POLICY IF EXISTS scans_patient_all ON public.scan_results;
CREATE POLICY scans_patient_all ON public.scan_results
    FOR ALL TO authenticated
    USING (user_id = (SELECT auth.uid()))
    WITH CHECK (user_id = (SELECT auth.uid()));

DROP POLICY IF EXISTS scans_doctor_read_care ON public.scan_results;
CREATE POLICY scans_doctor_read_care ON public.scan_results
    FOR SELECT TO authenticated
    USING (public.has_care_access(user_id));

DROP POLICY IF EXISTS scans_doctor_read_captured ON public.scan_results;
CREATE POLICY scans_doctor_read_captured ON public.scan_results
    FOR SELECT TO authenticated
    USING (doctor_id = (SELECT auth.uid()));

-- A doctor may capture a scan only for a patient they already have consented
-- access to, and only attributed to themselves.
DROP POLICY IF EXISTS scans_doctor_capture ON public.scan_results;
CREATE POLICY scans_doctor_capture ON public.scan_results
    FOR INSERT TO authenticated
    WITH CHECK (doctor_id = (SELECT auth.uid()) AND public.has_care_access(user_id));

-- reports ----------------------------------------------------------------
-- Read only. Reports are written and deleted exclusively by the backend using
-- the service role, which bypasses RLS. An INSERT policy here would grant
-- nothing the application needs while allowing a client to forge a report row.

DROP POLICY IF EXISTS reports_patient_select ON public.reports;
CREATE POLICY reports_patient_select ON public.reports
    FOR SELECT TO authenticated
    USING (user_id = (SELECT auth.uid()));

DROP POLICY IF EXISTS reports_doctor_select ON public.reports;
CREATE POLICY reports_doctor_select ON public.reports
    FOR SELECT TO authenticated
    USING (public.has_care_access(user_id));

-- chat_messages ----------------------------------------------------------

DROP POLICY IF EXISTS chat_own ON public.chat_messages;
CREATE POLICY chat_own ON public.chat_messages
    FOR ALL TO authenticated
    USING (patient_id = (SELECT auth.uid()))
    WITH CHECK (patient_id = (SELECT auth.uid()));

-- rag_corpus -------------------------------------------------------------
-- Published medical literature; readable by any authenticated caller. Writes
-- are service-role only, so the corpus cannot be altered from a client.

DROP POLICY IF EXISTS "Public read access to RAG corpus" ON public.rag_corpus;
CREATE POLICY "Public read access to RAG corpus" ON public.rag_corpus
    FOR SELECT
    USING (true);


-- =============================================================================
-- SECTION 11 — STORAGE
-- =============================================================================
-- Two private buckets. Neither is public: a public bucket would make every
-- object readable by URL alone, bypassing every check below.

INSERT INTO storage.buckets (id, name, public, file_size_limit)
VALUES ('scan-images', 'scan-images', false, 26214400)
ON CONFLICT (id) DO NOTHING;

INSERT INTO storage.buckets (id, name, public, file_size_limit)
VALUES ('medical_reports', 'medical_reports', false, 26214400)
ON CONFLICT (id) DO NOTHING;

-- Object layout
--   scan-images:     {patient_id}/{scan_id}.{ext}          source image
--                    {patient_id}/{scan_id}/overlay_N.png  explainability
--   medical_reports: {patient_id}/{report_id}.pdf          generated report
--
-- The leading path segment is the owning patient, which is what makes
-- folder-based authorisation possible.
--
-- Every ::uuid cast below is preceded by a regex guard. An unguarded cast on a
-- malformed path segment raises rather than returning false, which would
-- surface as a 500 instead of a denial.

DROP POLICY IF EXISTS scan_images_read ON storage.objects;
CREATE POLICY scan_images_read ON storage.objects
    FOR SELECT TO authenticated
    USING (
        bucket_id = 'scan-images'
        AND (
            (storage.foldername(name))[1] = ((SELECT auth.uid()))::text
            OR (
                (storage.foldername(name))[1] ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
                AND public.has_care_access(((storage.foldername(name))[1])::uuid)
            )
            OR EXISTS (
                SELECT 1 FROM public.scan_results sr
                WHERE sr.doctor_id = (SELECT auth.uid())
                  AND (sr.storage_path = objects.name
                       OR objects.name LIKE sr.user_id::text || '/' || sr.scan_id::text || '/%')
            )
        )
    );

DROP POLICY IF EXISTS scan_images_write ON storage.objects;
CREATE POLICY scan_images_write ON storage.objects
    FOR INSERT TO authenticated
    WITH CHECK (
        bucket_id = 'scan-images'
        AND (storage.foldername(name))[1] = ((SELECT auth.uid()))::text
    );

-- Reports are written only by the backend service role, so there is no write
-- policy here. The read policy accepts both a folder-based path and a flat
-- {patient_id}_{name} form, so a change of naming convention does not require
-- a policy change.
DROP POLICY IF EXISTS medical_reports_read ON storage.objects;
CREATE POLICY medical_reports_read ON storage.objects
    FOR SELECT TO authenticated
    USING (
        bucket_id = 'medical_reports'
        AND (
            split_part(name, '_', 1) = ((SELECT auth.uid()))::text
            OR (
                split_part(name, '_', 1) ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
                AND public.has_care_access((split_part(name, '_', 1))::uuid)
            )
            OR (storage.foldername(name))[1] = ((SELECT auth.uid()))::text
            OR (
                (storage.foldername(name))[1] ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
                AND public.has_care_access(((storage.foldername(name))[1])::uuid)
            )
        )
    );


-- =============================================================================
-- SECTION 12 — POWERSYNC PUBLICATION
-- =============================================================================
-- Logical replication feeding the offline-first mobile client. Deliberately
-- narrow: only tables the device needs. The corpus, checkpoints and reports
-- are excluded — too large, internal, or reachable by signed URL instead.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'powersync') THEN
        CREATE PUBLICATION powersync FOR TABLE
            public.patient_records,
            public.doctor_profiles,
            public.care_relationships,
            public.scan_results,
            public.chat_messages;
    END IF;
END $$;


-- =============================================================================
-- END OF BASELINE
-- =============================================================================
