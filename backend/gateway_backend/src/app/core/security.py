"""Comprehensive security and authentication validation utilities.

This module enforces access control across the gateway API by validating incoming
JSON Web Tokens (JWT) against the configured identity provider's JWKS. It also
provides an optional, strictly-controlled bypass mechanism for isolated development
environments.
"""

import time
import httpx
import logging
import secrets
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, ExpiredSignatureError, jwt

from .config import gateway_config

logger: logging.Logger = logging.getLogger(__name__)

security_scheme: HTTPBearer = HTTPBearer(auto_error=False)



class _JWKSCache:
    """Manages JWKS fetching with TTL caching and negative-result backoff."""
    def __init__(self, ttl: float = 900.0, backoff: float = 15.0):
        self._keys: Dict[str, Any] = {}
        self._expires_at: float = 0.0
        self._ttl: float = ttl
        self._backoff: float = backoff

    async def get_keys(self, url: str) -> Dict[str, Any]:
        now = time.monotonic()
        if self._keys and now < self._expires_at:
            return self._keys
            
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                self._keys = data
                self._expires_at = now + self._ttl
                logger.info("JWKS refreshed successfully.")
                return data
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
            logger.error("Failed to fetch JWKS from %s: %s", url, exc)
            self._expires_at = now + self._backoff
            if self._keys:
                return self._keys
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Identity provider unavailable: {str(exc)}"
            ) from exc

_jwks_cache = _JWKSCache()

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
) -> str:
    """Authenticates the incoming request via JWT validation or developer bypass.

    This dependency is injected into protected routing endpoints. It extracts
    the Bearer token, validates its structural integrity and cryptologic signature
    against the cached JWKS, and verifies expiration parameters. It returns the
    authenticated user's internal identifier upon success.

    Args:
        credentials (Optional[HTTPAuthorizationCredentials], optional): The bearer token
            extracted by FastAPI from the `Authorization` header. Defaults to the injected dependency.

    Returns:
        str: The internal universal identifier (UUID) for the authenticated user entity.

    Raises:
        HTTPException: Raises 401 Unauthorized if credentials are absent, invalid, expired,
            or if developer bypass is attempted in a production configuration.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token: str = credentials.credentials

    # Developer-token by‑pass – *only* active in DEV_MODE
    if gateway_config.dev_mode and gateway_config.dev_token_secret:
        if secrets.compare_digest(token, gateway_config.dev_token_secret):
            logger.info("Developer token accepted")
            # Note: This is a dummy valid UUID so it doesn't fail UUID DB constraints.
            # However, since it doesn't exist in auth.users, it will still fail RLS or FK constraints if used directly.
            return "00000000-0000-0000-0000-000000000000"

    # Supabase JWT validation
    try:
        unverified_header = jwt.get_unverified_header(token)
        if not unverified_header.get("kid"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing key ID (kid) in token header",
            )
            
        jwks = await _jwks_cache.get_keys(gateway_config.supabase_jwks_url)
        
        payload: dict = jwt.decode(
            token,
            jwks,
            algorithms=["ES256"],
            audience="authenticated",
            issuer="https://ppwnixwhaxpsqvufdggy.supabase.co/auth/v1",
        )
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except JWTError as exc:
        logger.error("JWT validation error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        ) from exc

    user_id: Optional[str] = payload.get("sub") or payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing identity claim",
        )
    return user_id
