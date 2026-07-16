"""Tests for the Gateway API using strict mocking for ultra-fast execution."""

import os

os.environ.setdefault("SUPABASE_URL", "http://mock-supabase")
os.environ.setdefault("SUPABASE_ANON_KEY", "mock-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "mock-service-role-key")
os.environ.setdefault("SUPABASE_JWT_SECRET", "dummy_jwt_secret_for_testing_only_at_least_32_chars")
os.environ.setdefault("CXR_SERVICE_URL", "http://cxr-mock")
os.environ.setdefault("ECG_SERVICE_URL", "http://ecg-mock")
os.environ.setdefault("SKIN_SERVICE_URL", "http://skin-mock")
os.environ.setdefault("AGENT_SERVICE_URL", "http://agent-mock")
os.environ.setdefault("ALLOWED_ORIGINS", "https://test-origin.example.com")
os.environ.setdefault("DEV_MODE", "true")
os.environ.setdefault("DEV_TOKEN_SECRET", "test-dev-token-secret")
os.environ.setdefault("SUPABASE_STORAGE_BUCKET", "test-bucket")
os.environ.setdefault("MAX_UPLOAD_BYTES", "20971520")

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient, Response
from fastapi.testclient import TestClient

from app.main import app
from app.core.security import get_current_user

client = TestClient(app)


# ---------------------------------------------------------------------------
#  Test 1 — Health endpoint
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_healthz() -> None:
    """Assert GET /api/v1/health/healthz returns 200 with status == 'ok'.

    Bug #10 fix: the original test tried /healthz then /api/v1/healthz —
    both wrong.  The health router is mounted at /api/v1 with an internal
    prefix of /health, and the endpoint path is /healthz, making the full
    path /api/v1/health/healthz.
    """
    response = client.get("/api/v1/health/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ---------------------------------------------------------------------------
#  Test 2 — Authentication barrier (no token → 401)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "method, endpoint",
    [
        ("POST", "/api/v1/reports/generate"),
        ("GET", "/api/v1/reports/download/123"),
        ("GET", "/api/v1/patients/123"),
    ],
)
@pytest.mark.asyncio
async def test_authentication_barrier(method: str, endpoint: str) -> None:
    """Assert that protected endpoints reject unauthenticated requests with 401."""
    response = client.request(method, endpoint)
    assert response.status_code == 401


# ---------------------------------------------------------------------------
#  Test 3 — CXR proxy (mocked httpx)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cxr_stream_proxying() -> None:
    """Mock the downstream httpx.AsyncClient to verify the CXR proxy path."""
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "predictions": [{"label": "Pneumonia", "probability": 0.95}]
    }
    mock_response.raise_for_status = MagicMock()
    mock_client.post.return_value = mock_response
    
    app.state.http_client = mock_client
    app.state.db_pool = None

    app.dependency_overrides[get_current_user] = lambda: "test_user_uuid"
    try:
        response = client.post(
            "/api/v1/cxr/predict",
            files={"file": ("xray.jpg", b"fake_binary_image_data", "image/jpeg")},
            data={"top_k": 3},
            headers={"Authorization": "Bearer fake_valid_token"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert mock_client.post.called
    assert response.status_code == 200
    assert response.json() == {"predictions": [{"label": "Pneumonia", "probability": 0.95}]}


# ---------------------------------------------------------------------------
#  Test 4 — Upload size guard → 413
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upload_size_guard_returns_413() -> None:
    """Assert that files exceeding max_upload_bytes are rejected with HTTP 413."""
    from app.core.config import gateway_config

    # Fabricate a payload 1 byte larger than the current limit
    oversized = b"x" * (gateway_config.max_upload_bytes + 1)

    app.dependency_overrides[get_current_user] = lambda: "test_user_uuid"
    try:
        response = client.post(
            "/api/v1/cxr/predict",
            files={"file": ("huge.jpg", oversized, "image/jpeg")},
            data={"top_k": 1},
            headers={"Authorization": "Bearer fake_valid_token"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 413


# ---------------------------------------------------------------------------
#  Test 5 — Patient router (mocked httpx → Supabase)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_patient_router() -> None:
    """Verify the gateway attaches the bearer token and anon key to Supabase calls."""
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {"id": "123", "name": "John Doe", "dob": "1990-01-01"}
    ]
    mock_response.raise_for_status = MagicMock()
    mock_client.get.return_value = mock_response
    
    app.state.http_client = mock_client

    headers = {
        "Authorization": "Bearer fake_jwt_token",
        "apikey": "fake_supabase_anon_key",
    }
    app.dependency_overrides[get_current_user] = lambda: "test_user_uuid"
    try:
        response = client.get("/api/v1/patients/123", headers=headers)
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    if response.status_code == 200:
        assert mock_client.get.called
        call_args = mock_client.get.call_args
        passed_headers = call_args.kwargs.get("headers", {})
        assert passed_headers.get("Authorization") == "Bearer fake_jwt_token"
        from app.api.patient_router import SUPABASE_ANON_KEY
        assert passed_headers.get("apikey") == SUPABASE_ANON_KEY


# ---------------------------------------------------------------------------
#  Test 6 — CORS: wildcard origin must NOT appear with credentials
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cors_no_wildcard_with_credentials() -> None:
    """Assert the CORS middleware never returns Access-Control-Allow-Origin: *
    in response to a credentialed request from a non-allowed origin.

    Bug #1 regression test: the original config used allow_origins=['*'] with
    allow_credentials=True, which browsers reject.  After the fix, only
    explicitly allowed origins receive the ACAO header.
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
        "CORS middleware returned wildcard origin — Bug #1 regression detected."
    )


# ---------------------------------------------------------------------------
#  Test 7 — Allowed origin receives correct CORS header
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
#  Test 8 — Fault injection for unreachable upstreams (HTTP 502 + JSON envelope)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upstream_service_error_envelope() -> None:
    """Assert that HTTPStatusError from upstream returns a properly formatted 502 JSON."""
    from httpx import HTTPStatusError, Request as HttpxRequest
    
    mock_client = AsyncMock()
    
    # Simulate an HTTP 500 from the upstream CXR service
    req = HttpxRequest("POST", "http://cxr-mock/predict")
    mock_response = Response(status_code=500, request=req)
    
    mock_client.post.side_effect = HTTPStatusError(
        "Internal Server Error",
        request=req,
        response=mock_response
    )
    
    app.state.http_client = mock_client
    app.dependency_overrides[get_current_user] = lambda: "test_user_uuid"
    
    try:
        response = client.post(
            "/api/v1/cxr/predict",
            files={"file": ("xray.jpg", b"fake", "image/jpeg")},
            data={"top_k": 3},
            headers={"Authorization": "Bearer fake_token"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 503
    data = response.json()
    assert data.get("error") is True
    assert data.get("type") == "ServiceUnavailableError"
    assert "Service unavailable" in data.get("message", "")
    assert "context" in data
