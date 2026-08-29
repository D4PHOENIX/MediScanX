-- 0115_care_relationship_expiry_sweep.sql
--
-- The PowerSync doctor_care bucket scopes on status = 'active' only. has_care_access
-- additionally requires expires_at IS NULL OR expires_at > now(). The sync rule cannot
-- carry that arm: parameter queries must be deterministic and re-evaluable, and no event
-- fires at the instant expires_at passes, so the bucket would never close on its own.
--
-- Expiry therefore becomes a state transition. Once status leaves 'active' the existing
-- sync rule is sufficient: the bucket closes and PowerSync evicts the rows from the
-- device, which is the same path revocation already uses correctly.
--
-- 'revoked' is reused rather than adding an 'expired' value, which would require altering
-- care_relationships_status_check and reviewing every status filter in the codebase.
-- ended_at records when the row closed; a non-null expires_at distinguishes an expiry
-- from a manual revoke. A dedicated 'expired' state is a post-defence migration.
--
-- The read-time expiry checks in has_care_access, get_triage, report_service,
-- report_router and list_care_relationships all REMAIN. If this job stalls the API still
-- refuses. Defence in depth, not replacement.
--
-- authenticated is deliberately NOT granted: no end user should invoke a system sweep.
-- Note that Supabase default privileges grant EXECUTE to anon at creation and
-- REVOKE FROM PUBLIC does not remove it, so anon is revoked explicitly.

CREATE EXTENSION IF NOT EXISTS pg_cron;

CREATE OR REPLACE FUNCTION public.expire_care_relationships()
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_temp'
AS $$
DECLARE
    v_count integer;
BEGIN
    UPDATE public.care_relationships
       SET status   = 'revoked',
           ended_at = COALESCE(ended_at, now())
     WHERE status = 'active'
       AND expires_at IS NOT NULL
       AND expires_at <= now();

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.expire_care_relationships() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.expire_care_relationships() FROM anon;
REVOKE EXECUTE ON FUNCTION public.expire_care_relationships() FROM authenticated;
GRANT  EXECUTE ON FUNCTION public.expire_care_relationships() TO service_role;;