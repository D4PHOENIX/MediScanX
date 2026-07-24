-- 0008_add_storage_path_to_scan_results.sql
-- Adds the deterministic storage_path column to scan_results to decouple from image_url parsing.

ALTER TABLE scan_results ADD COLUMN storage_path TEXT;

-- Backfill existing rows by extracting the path directly from the public image_url.
-- This accurately preserves any existing extensions (.png, .jpg, etc) without guessing.
UPDATE scan_results 
SET storage_path = substring(image_url from 'scan-images/(.*)$') 
WHERE image_url IS NOT NULL;

-- Ensure no existing rows are left with a NULL storage_path where an image_url exists.
DO $$
DECLARE
    null_count INT;
BEGIN
    SELECT count(*) INTO null_count FROM scan_results WHERE image_url IS NOT NULL AND storage_path IS NULL;
    IF null_count > 0 THEN
        RAISE EXCEPTION 'Backfill failed: % rows have a NULL storage_path after backfilling from image_url', null_count;
    END IF;
END $$;
