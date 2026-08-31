"""Request-scoped Supabase client factory.

Constructs a per-request ``supabase.AsyncClient`` initialised with the
**anon key** and the caller's ``Authorization`` bearer token.  Queries made
through this client run as the ``authenticated`` role and are subject to all
RLS policies defined on the target table.

Contrast with ``app.state.supabase_client``, which is built with the
``service_role`` key at startup and bypasses RLS entirely.  That client is
legitimate for storage operations (the medical_reports bucket has its own
object-level policy) but must never be used for ``public.reports`` reads.
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status
from supabase import create_async_client
from supabase._async.client import AsyncClient as SupabaseAsyncClient

from app.core.config import gateway_config


def _extract_bearer(request: Request) -> str:
    """Extract the raw bearer token from the incoming request.

    Raises 401 immediately if the header is absent or malformed so callers
    never reach a database operation without a valid identity token.

    Args:
        request: The current FastAPI request object.

    Returns:
        str: The raw JWT string (everything after ``Bearer ``).

    Raises:
        HTTPException: 401 if the ``Authorization`` header is missing or does
            not follow the ``Bearer <token>`` scheme.
    """
    auth_header: str | None = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return auth_header[len("Bearer "):]


async def make_user_client(request: Request) -> SupabaseAsyncClient:
    """Build a request-scoped Supabase client carrying the caller's JWT.

    The client uses the **anon key** so PostgREST evaluates RLS policies for
    the ``authenticated`` role.  The caller's bearer token is injected via the
    ``Authorization`` header at client construction time, making ``auth.uid()``
    resolve correctly inside policy expressions such as
    ``reports_patient_select`` and ``reports_doctor_select``.

    This function raises 401 eagerly if the request carries no bearer token,
    so downstream code never reaches a database call without a verified identity.

    Args:
        request: The current FastAPI request object.

    Returns:
        SupabaseAsyncClient: A fresh AsyncClient scoped to the caller's identity.

    Raises:
        HTTPException: 401 if ``Authorization: Bearer <token>`` is absent.
    """
    from supabase.lib.client_options import AsyncClientOptions

    token: str = _extract_bearer(request)
    options = AsyncClientOptions(headers={"Authorization": f"Bearer {token}"})
    client: SupabaseAsyncClient = await create_async_client(
        gateway_config.supabase_url,
        gateway_config.supabase_publishable_key,
        options=options,
    )
    return client
