"""Supabase Storage upload service for scan image persistence.

Provides an asynchronous interface to upload binary image files to a configured
Supabase Storage bucket using the service-role key, bypassing RLS so that the
gateway can write on behalf of any authenticated user.
"""

import logging
import mimetypes
from typing import Optional

from httpx import AsyncClient, HTTPStatusError, RequestError

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

    All methods are static — there is no per-instance state.  The
    ``httpx.AsyncClient`` stored on ``app.state`` is passed in explicitly
    so that the gateway's single shared client handles all outbound I/O.
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
        http_client: AsyncClient,
        supabase_url: str,
        service_role_key: str,
        bucket: str,
        user_id: str,
        scan_id: str,
        file_bytes: bytes,
        content_type: Optional[str] = None,
    ) -> str:
        """Uploads a scan image to Supabase Storage and returns its public URL.

        Issues a ``PUT`` to the Supabase Storage REST API using the
        ``service_role_key`` so that RLS is bypassed at the storage layer.
        The object is created with public read access, matching the expected
        access pattern for the Flutter UI (direct HTTPS fetch by URL).

        Args:
            http_client: The shared ``httpx.AsyncClient`` from ``app.state``.
            supabase_url: Base URL of the Supabase project (e.g. ``https://xyz.supabase.co``).
            service_role_key: The Supabase service-role secret key.
            bucket: Target storage bucket name (e.g. ``"scan-images"``).
            user_id: The authenticated user's UUID — used to namespace the object path.
            scan_id: The scan's UUID — used as the filename stem.
            file_bytes: Raw binary content of the image file.
            content_type: MIME type of the image; defaults to ``"image/png"``.

        Returns:
            str: The public HTTPS URL of the stored object.

        Raises:
            RuntimeError: If the Supabase Storage upload fails with a non-2xx response.
        """
        resolved_content_type = content_type or "image/png"
        if resolved_content_type not in _ALLOWED_CONTENT_TYPES:
            logger.warning(
                "Unexpected content_type '%s' for scan %s — coercing to image/png",
                resolved_content_type,
                scan_id,
            )
            resolved_content_type = "image/png"

        object_path = StorageService._build_object_path(user_id, scan_id, resolved_content_type)
        upload_url = f"{supabase_url}/storage/v1/object/{bucket}/{object_path}"

        try:
            resp = await http_client.put(
                upload_url,
                content=file_bytes,
                headers={
                    "Authorization": f"Bearer {service_role_key}",
                    "Content-Type": resolved_content_type,
                    # Instruct Supabase Storage to overwrite any existing object at
                    # this path, enabling idempotent re-uploads on retry.
                    "x-upsert": "true",
                },
            )
            resp.raise_for_status()
        except (HTTPStatusError, RequestError) as exc:
            logger.error(
                "Supabase Storage upload failed for scan_id=%s: %s", scan_id, exc
            )
            raise RuntimeError(
                f"Storage upload failed for scan {scan_id}: {exc}"
            ) from exc

        # Construct the authenticated URL for the stored object.
        # Since the bucket is private, this URL requires the Flutter client
        # to attach `Authorization: Bearer <JWT>` to the image download request.
        auth_url = f"{supabase_url}/storage/v1/object/authenticated/{bucket}/{object_path}"
        logger.info("Scan image stored at %s", auth_url)
        return auth_url
