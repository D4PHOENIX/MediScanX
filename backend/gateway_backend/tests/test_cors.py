"""Tests for the Gateway API CORS."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

@pytest.mark.asyncio
async def test_cors_no_wildcard_with_credentials() -> None:
    """Assert the CORS middleware never returns Access-Control-Allow-Origin: *
    in response to a credentialed request from a non-allowed origin.

    Asserts that CORS is configured securely without wildcard origins when allow_credentials=True.
    Browsers reject wildcard origins when credentials are allowed. 
    Only the explicit ORIGINS array should be permitted.
    """
    # An origin that is NOT in the allowed list should not get ACAO back
    response = client.options(
        "/api/v1/health/healthz",
        headers={
            "Origin": "https://evil-site.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    acao = response.headers.get("access-control-allow-origin", "")
    # Must not be wildcard
    assert acao != "*", (
        "CORS middleware returned wildcard origin when credentials are allowed."
    )

@pytest.mark.asyncio
async def test_cors_allowed_origin_reflects_correctly() -> None:
    """Assert that a request from an allowed origin gets the correct ACAO header."""
    from app.core.config import gateway_config

    allowed = gateway_config.allowed_origins.split(",")[0].strip()
    response = client.options(
        "/api/v1/health/healthz",
        headers={
            "Origin": allowed,
            "Access-Control-Request-Method": "GET",
        },
    )
    acao = response.headers.get("access-control-allow-origin", "")
    assert acao == allowed, (
        f"Expected ACAO={allowed!r}, got {acao!r}. "
        "The CORSMiddleware may not be reflecting the origin correctly."
    )
