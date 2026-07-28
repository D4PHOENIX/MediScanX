"""Supabase Storage upload service for scan image persistence.

Provides an asynchronous interface to upload binary image files to a configured
Supabase Storage bucket using the ``supabase-py`` async SDK.  The SDK client is
initialised with the ``service_role_key`` so that Row-Level Security is bypassed,
allowing the gateway to write on behalf of any authenticated user.

This module supports both the new ``sb_secret_*`` API keys and the legacy
JWT-format keys — the SDK handles auth translation internally.
"""

import logging
import mimetypes
from typing import Optional

from supabase._async.client import AsyncClient as SupabaseAsyncClient

logger: logging.Logger = logging.getLogger(__name__)

# Supported content-types for scan images
_ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset({
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/bmp",
    "image/tiff",
    "application/octet-stream",  # fallback for raw binary uploads
})


class StorageService:
    """Async interface for uploading scan images to Supabase Storage.

    All methods are static — there is no per-instance state.  The shared
    ``supabase.AsyncClient`` stored on ``app.state`` is passed in explicitly
    so that the gateway uses a single SDK client for all storage I/O.
    """

    @staticmethod
    def _build_object_path(user_id: str, scan_id: str, content_type: str) -> str:
        """Constructs a deterministic, collision-free storage path.

        Path format: ``{user_id}/{scan_id}.{ext}``

        Scoping uploads under the user's UUID makes it trivial to apply
        per-user Supabase Storage RLS policies in the future.

        Args:
            user_id: The authenticated user's UUID.
            scan_id: The scan's UUID (client- or server-generated).
            content_type: The MIME type of the uploaded file.

        Returns:
            str: The object path within the bucket (no leading slash).
        """
        extension = mimetypes.guess_extension(content_type) or ".bin"
        # Normalise common extensions that mimetypes maps oddly
        _EXT_MAP = {".jpe": ".jpg", ".jpeg": ".jpg", ".tiff": ".tif"}
        extension = _EXT_MAP.get(extension, extension)
        return f"{user_id}/{scan_id}{extension}"

    @staticmethod
    async def upload_scan_image(
        supabase_client: SupabaseAsyncClient,
        bucket: str,
        user_id: str,
        scan_id: str,
        file_bytes: bytes,
        content_type: Optional[str] = None,
        object_path: Optional[str] = None,
    ) -> tuple[str, str]:
        """Uploads a scan image to Supabase Storage and returns its public URL and object path.

        Uses the ``supabase-py`` async SDK which internally handles auth
        token translation, supporting both legacy JWT keys and the newer
        ``sb_secret_*`` API keys.

        Args:
            supabase_client: The shared ``supabase.AsyncClient`` from ``app.state``.
            bucket: Target storage bucket name (e.g. ``"scan-images"``).
            user_id: The authenticated user's UUID — used to namespace the object path.
            scan_id: The scan's UUID — used as the filename stem.
            file_bytes: Raw binary content of the image file.
            content_type: MIME type of the image; defaults to ``"image/png"``.

        Returns:
            tuple[str, str]: The public HTTPS URL of the stored object and the internal object path.

        Raises:
            RuntimeError: If the Supabase Storage upload fails.
        """
        resolved_content_type = content_type or "image/png"
        if resolved_content_type not in _ALLOWED_CONTENT_TYPES:
            logger.warning(
                "Unexpected content_type '%s' for scan %s — coercing to image/png",
                resolved_content_type,
                scan_id,
            )
            resolved_content_type = "image/png"

        if object_path is None:
            object_path = StorageService._build_object_path(user_id, scan_id, resolved_content_type)
        elif not object_path.startswith(f"{user_id}/"):
            raise ValueError(f"object_path override must start with {user_id}/ to enforce tenant isolation")

        try:
            storage_bucket = supabase_client.storage.from_(bucket)
            await storage_bucket.upload(
                path=object_path,
                file=file_bytes,
                file_options={
                    "content-type": resolved_content_type,
                    # Instruct Supabase Storage to overwrite any existing object at
                    # this path, enabling idempotent re-uploads on retry.
                    "x-upsert": "true",
                },
            )
        except Exception as exc:
            logger.error(
                "Supabase Storage upload failed for scan_id=%s: %s",
                scan_id,
                exc,
            )
            raise RuntimeError(
                f"Storage upload failed for scan {scan_id}: {exc}"
            ) from exc

        # Construct the public URL for the stored object.
        # Since the bucket is public, the Flutter client can fetch directly via HTTPS.
        public_url: str = await storage_bucket.get_public_url(object_path)
        logger.info("Scan image stored at %s with path %s", public_url, object_path)
        return public_url, object_path
