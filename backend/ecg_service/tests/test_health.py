"""Tests for the ECG Inference Service using pure mocking for ultra-fast execution."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
#  Test 6 — Engine-not-ready returns 503
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_engine_not_ready_returns_503(test_app, async_client: AsyncClient) -> None:
    """Assert that the readiness guard returns 503 when engine.ready is False."""
    from app.api.routes import get_engine
    import app.api.routes as routes_module

    # Temporarily mark the global engine as not ready
    original_engine = routes_module.ecg_engine
    routes_module.ecg_engine = None

    try:
        response = await async_client.get("/healthz")
        assert response.status_code == 503
    finally:
        routes_module.ecg_engine = original_engine


# ---------------------------------------------------------------------------
#  Test 7 — /healthz returns 200 when engine is ready
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_healthz_when_ready(test_app, async_client: AsyncClient) -> None:
    """Assert /healthz returns 200 and status=healthy when engine is ready."""
    response = await async_client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
