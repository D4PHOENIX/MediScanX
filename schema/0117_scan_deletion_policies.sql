-- =============================================================================
-- Migration 0117 — Owner-scoped DELETE policy on scan-images storage objects
-- =============================================================================
--
-- Context
-- -------
-- Task B41 adds DELETE /api/v1/scans/{scan_id}. Currently, storage deletion runs
-- via StorageService.delete_scan_objects using the service-role client, which
-- bypasses RLS. Ownership enforcement today relies on an application-layer
-- {user_id}/ prefix guard inside delete_scan_objects.
--
-- This migration adds an owner-scoped DELETE policy to the scan-images bucket.
-- Because the endpoint uses service-role, this policy is NOT evaluated today.
-- It is added as defence in depth and lays the groundwork for a future migration
-- off service-role to the authenticated (anon-key + caller-JWT) path.
--
-- Confirmed state: storage.objects currently carries scan_images_write (INSERT),
-- scan_images_read (SELECT), and medical_reports_read (SELECT). No DELETE policy
-- exists on any bucket. This will be the first.
--
-- Bucket: scan-images (private)
-- Object layout:
--   {patient_uuid}/{scan_uuid}.{ext}           raw source image
--   {patient_uuid}/{scan_uuid}/overlay_N.png   XAI explainability overlay
--
-- The first path segment is always the owning patient's UUID. The policy gates
-- deletion on that segment matching the caller's auth.uid(). Expressed as a
-- text equality rather than a ::uuid cast so that a malformed first segment
-- returns false rather than raising a cast exception.
--
-- Regex guard note
-- ----------------
-- The USING clause performs:
--
--   (storage.foldername(name))[1] = (SELECT auth.uid())::text
--
-- The left-hand side is the first path segment as text. The right-hand side
-- casts auth.uid() (a uuid type) to text — that cast is always safe. No ::uuid
-- cast is applied to the user-supplied path segment, so no regex guard is needed
-- in this clause. If a ::uuid cast on a path segment is ever added here (e.g. to
-- call has_care_access()), a regex guard of the form:
--
--   (storage.foldername(name))[1]
--     ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
--
-- MUST precede that cast, or a malformed segment raises a 500 instead of a
-- denial. See scan_images_read and medical_reports_read for the established
-- guard pattern.
--
-- Scope
-- -----
-- Owner-only. No care-relationship branch: a doctor cannot delete a patient's
-- scan objects through this policy.
--
-- Out of scope
-- ------------
-- No DELETE policy is added to medical_reports. Deleting a scan does not delete
-- its derived reports (product decision, B41). Reports are immutable clinical
-- artifacts whose storage objects remain service-role-managed.
--
-- Do not apply this migration — leave it for the DBA / deployment pipeline.
-- =============================================================================

BEGIN;

DROP POLICY IF EXISTS scan_images_delete ON storage.objects;
CREATE POLICY scan_images_delete ON storage.objects
    FOR DELETE TO authenticated
    USING (
        bucket_id = 'scan-images'
        AND (storage.foldername(name))[1] = (SELECT auth.uid())::text
    );

COMMIT;
