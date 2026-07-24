"""Comprehensive security and authentication validation utilities for the Agent Service.

This module enforces access control by validating incoming JSON Web Tokens (JWT) 
against the configured identity provider's JWKS. It also provides an optional, 
strictly-controlled bypass mechanism for isolated development environments.
"""

import json
import logging
import secrets
from functools import lru_cache
from typing import Any, Dict, Optional
from urllib.request import urlopen

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, ExpiredSignatureError, jwt

from .config import AgentConfig

logger: logging.Logger = logging.getLogger(__name__)

security_scheme: HTTPBearer = HTTPBearer(auto_error=False)

# To avoid circular imports or relying on app.state here, we instantiate the config or we expect it.
# Actually, it's better to instantiate one globally for security.
agent_config = AgentConfig()


@lru_cache(maxsize=1)
def get_jwks(jwks_url: str) -> Dict[str, Any]:
    """Retrieves and caches the JSON Web Key Set (JWKS) from the identity provider.

    Args:
        jwks_url (str): The absolute URL endpoint hosting the JWKS payload.

    Returns:
        Dict[str, Any]: The parsed JSON representation of the key set.
    """
    with urlopen(jwks_url) as response:
        return json.loads(response.read().decode("utf-8"))


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
) -> str:
    """Authenticates the incoming request via JWT validation or developer bypass.

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
    if agent_config.dev_mode and agent_config.dev_token_secret:
        if secrets.compare_digest(token, agent_config.dev_token_secret):
            logger.info("Developer token accepted")
            # Note: This is a dummy valid UUID so it doesn't fail UUID DB constraints.
            # However, since it doesn't exist in auth.users, it will still fail RLS or FK constraints if used directly.
            return "00000000-0000-0000-0000-000000000000"

    # Supabase JWT validation
    if not agent_config.supabase_jwks_url:
        logger.error("SUPABASE_JWKS_URL is not configured for JWT validation.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server identity provider configuration error",
        )

    try:
        unverified_header = jwt.get_unverified_header(token)
        if not unverified_header.get("kid"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing key ID (kid) in token header",
            )
            
        jwks = get_jwks(agent_config.supabase_jwks_url)
        
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
