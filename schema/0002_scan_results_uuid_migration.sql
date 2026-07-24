-- ==============================================================================
-- MediScanX - Migration 0002: scan_results UUID Promotion & Edge-Sync Support
-- File: 0002_scan_results_uuid_migration.sql
-- Prerequisite: scan_results table must be EMPTY (0 rows).
--   Run: SELECT COUNT(*) FROM scan_results; to verify before executing.
-- ==============================================================================

BEGIN;

-- The `scan_id` UUID column has always been the functional primary key.
-- The `id` BIGINT column is vestigial and prevents offline client UUID generation
-- because mobile clients cannot predict the server-assigned int8 value.
ALTER TABLE scan_results DROP COLUMN IF EXISTS id;


-- Distinguishes scans inferred via the cloud gateway pipeline from scans
-- inferred locally on-device via TFLite and synced later.
--   'cloud' = gateway_backend → ML microservice → INSERT
--   'edge'  = Flutter TFLite → pending_sync outbox → POST /sync/edge-inference → INSERT
ALTER TABLE scan_results
    ADD COLUMN IF NOT EXISTS inference_source TEXT NOT NULL DEFAULT 'cloud'
    CONSTRAINT chk_inference_source CHECK (inference_source IN ('cloud', 'edge'));


-- Ensures the updated_at timestamp is always refreshed on any row mutation,
-- which is critical for PowerSync change-data-capture diff resolution.
CREATE OR REPLACE FUNCTION public.update_updated_at_column()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = timezone('utc'::text, now());
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_scan_results_updated_at ON scan_results;
CREATE TRIGGER trg_scan_results_updated_at
    BEFORE UPDATE ON scan_results
    FOR EACH ROW
    EXECUTE FUNCTION public.update_updated_at_column();


-- Cover the three dominant query access patterns for the scan history UI.
CREATE INDEX IF NOT EXISTS idx_scan_results_user_id
    ON scan_results(user_id);

CREATE INDEX IF NOT EXISTS idx_scan_results_doctor_id
    ON scan_results(doctor_id)
    WHERE doctor_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_scan_results_scan_date
    ON scan_results(scan_date DESC);

CREATE INDEX IF NOT EXISTS idx_scan_results_inference_source
    ON scan_results(inference_source);


-- Required for PowerSync to emit DELETE events with the full old row, enabling
-- correct diff resolution on the mobile SQLite replica.
ALTER TABLE scan_results REPLICA IDENTITY FULL;


COMMIT;
