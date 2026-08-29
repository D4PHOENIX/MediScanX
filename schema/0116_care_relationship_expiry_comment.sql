-- 0116_care_relationship_expiry_comment.sql
-- Documents the expiry behavior for care relationships.

COMMENT ON COLUMN public.care_relationships.expires_at IS 'The QR-claim path sets a 7-day TTL. The request_care/respond_to_care RPCs leave this NULL (indefinite until revoked).';
