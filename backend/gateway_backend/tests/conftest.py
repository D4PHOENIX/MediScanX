"""Pytest fixtures for Gateway API tests."""

import os

# -----------------------------------------------------------------------
# Set ALL mandatory GatewayConfig fields BEFORE any app module is imported.
# GatewayConfig is a pydantic-settings BaseSettings with four required
# string fields (no defaults).  Importing app.main triggers GatewayConfig()
# in security.py at module load time.  Any missing mandatory field raises a
# ValidationError at collection time, aborting the entire test run. 
# -----------------------------------------------------------------------
os.environ.setdefault("SUPABASE_URL", "http://mock-supabase")
os.environ.setdefault("SUPABASE_ANON_KEY", "mock-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "mock-service-role-key")
os.environ.setdefault("CXR_SERVICE_URL", "http://cxr-mock")
os.environ.setdefault("ECG_SERVICE_URL", "http://ecg-mock")
os.environ.setdefault("SKIN_SERVICE_URL", "http://skin-mock")
os.environ.setdefault("AGENT_SERVICE_URL", "http://agent-mock")
# Allow the dev-token bypass in tests so individual tests can use it without
# constructing a real HS256 JWT.
os.environ.setdefault("DEV_MODE", "true")
    
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
def test_app():
    """Yield the FastAPI application instance for integration tests."""
    return app


@pytest.fixture
async def async_client(test_app):
    """Return an httpx AsyncClient connected to the FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.fixture(autouse=True)
def mock_jwks():
    """Mock the JWKS fetcher to prevent external HTTP calls during testing."""
    dummy_jwks = {"keys": [{"kid": "test-kid", "kty": "EC", "crv": "P-256", "x": "dummy", "y": "dummy"}]}
    with patch("app.core.security.get_jwks", return_value=dummy_jwks):
        yield
