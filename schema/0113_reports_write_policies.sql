-- MERGE ORDER: This migration must be applied to the database BEFORE deploying the gateway API changes from this branch.
-- Migration: 0113_reports_write_policies.sql
--
-- Adds owner-scoped INSERT, UPDATE, and DELETE policies on public.reports.
--
-- Background
-- ----------
-- The reports table was intentionally created with read-only RLS in the preceding
-- migration (create_reports_table_with_read_only_rls - 20260806093327), relying on
-- the service-role gateway client to bypass RLS for all mutations.  Task B39
-- repoints the gateway to a request-scoped (anon-key + caller-JWT) client for
-- every public.reports operation.  That client runs as the ``authenticated``
-- role, so RLS is now enforced.  These write policies are new surface rather
-- than a restoration. Without them, the INSERT and DELETE calls from the gateway
-- would be silently blocked (permissive-model default: deny), even when the caller
-- is the legitimate owner.
--
-- Policy shape
-- ------------
-- INSERT: only the patient themselves can create a row with their own user_id.
--   WITH CHECK ensures the row's user_id matches the inserting principal.
--
-- UPDATE: owner-only.  USING restricts which rows are visible for update;
--   WITH CHECK prevents a caller from changing user_id to someone else's UUID.
--   No application path currently updates reports, but the policy is added for
--   completeness and defence in depth.
--
-- DELETE: owner-only.  Only the patient who owns a report can delete it.
--   Mirrors the shape of reports_patient_select.
--
-- Notes
-- -----
-- * has_care_access() is NOT granted for writes.  A doctor with care access
--   can read a patient's reports but cannot insert, update, or delete them.
-- * The UPDATE policy uses the same USING / WITH CHECK predicate.  A future
--   doctor-delegated update path would need its own policy.
-- * generated_by is NOT constrained here because a doctor generating a report
--   on behalf of a patient is a legitimate workflow (INSERT user_id = patient,
--   generated_by = doctor).

BEGIN;

-- INSERT policy ---------------------------------------------------------------
-- The caller may only insert a report row whose user_id equals their own uid.
-- This prevents a patient from forging a row on behalf of another user.

DROP POLICY IF EXISTS reports_patient_insert ON public.reports;
CREATE POLICY reports_patient_insert ON public.reports
    FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT auth.uid()));

-- UPDATE policy ---------------------------------------------------------------
-- The caller may only update their own rows and may not reassign user_id.

DROP POLICY IF EXISTS reports_patient_update ON public.reports;
CREATE POLICY reports_patient_update ON public.reports
    FOR UPDATE TO authenticated
    USING  (user_id = (SELECT auth.uid()))
    WITH CHECK (user_id = (SELECT auth.uid()));

-- DELETE policy ---------------------------------------------------------------
-- Only the patient who owns a report may delete it.  Mirrors reports_patient_select.

DROP POLICY IF EXISTS reports_patient_delete ON public.reports;
CREATE POLICY reports_patient_delete ON public.reports
    FOR DELETE TO authenticated
    USING (user_id = (SELECT auth.uid()));

COMMIT;
