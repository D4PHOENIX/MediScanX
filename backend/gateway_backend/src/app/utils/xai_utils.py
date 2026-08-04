"""XAI explainability utilities for the MediScanX Gateway.

Provides pure helper functions for building authenticated storage URLs
for XAI overlay images stored in the Supabase ``scan-images`` bucket.

URL form required by the RLS policy ``scan_images_read``:

    {SUPABASE_URL}/storage/v1/object/authenticated/scan-images/{xai_path}

The client attaches the user's Supabase JWT as a Bearer token; Postgres
then evaluates ``scan_images_read`` with that user's identity, enforcing
per-patient and care-relationship access control.

Important:
  - Never use signed URLs.  A signed URL carries service-role authority
    and bypasses RLS entirely.
  - Never use public URLs.  The ``scan-images`` bucket is private.
  - Path separators (``/``) must remain separators — do not percent-encode them.
"""

from typing import Optional

from app.core.config import gateway_config

# The private storage bucket that holds all scan images and overlays.
# Value is read from SUPABASE_STORAGE_BUCKET env var via gateway_config.
_SCAN_IMAGES_BUCKET: str = gateway_config.supabase_storage_bucket


def build_xai_authenticated_url(xai_path: Optional[str]) -> Optional[str]:
    """Convert a stored ``xai_path`` into an authenticated Supabase Storage URL.

    The returned URL is of the form::

        {SUPABASE_URL}/storage/v1/object/authenticated/{bucket}/{xai_path}

    The client must attach the user's JWT as a ``Bearer`` token.  Supabase
    evaluates the ``scan_images_read`` RLS policy with the caller's identity.

    Rules:
    - Returns ``None`` when ``xai_path`` is ``None`` or empty string.
    - Path separators (``/``) in ``xai_path`` are preserved verbatim; they
      are not percent-encoded because they represent folder hierarchy within
      the bucket, not literal slash characters in a single path segment.
    - UUID path components are not encoded; they contain only hex digits and
      hyphens, which are unreserved characters in RFC 3986.
    - Never produces a signed URL, a public URL, or a partial URL.

    Args:
        xai_path: The bucket-relative object path (e.g.
            ``"<user_id>/<scan_id>/overlay_0.png"``), or ``None``.

    Returns:
        The authenticated HTTPS URL string, or ``None`` if ``xai_path`` is
        absent or empty.
    """
    if not xai_path:
        return None

    base_url = gateway_config.supabase_url.rstrip("/")
    return f"{base_url}/storage/v1/object/authenticated/{_SCAN_IMAGES_BUCKET}/{xai_path}"
