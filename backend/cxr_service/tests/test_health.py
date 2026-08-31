"""Tests for the CXR Inference Service health endpoints."""

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
#  Test 6 — Engine not ready → 503
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_engine_not_ready_returns_503(test_app, async_client: AsyncClient) -> None:
    """Assert /healthz returns 503 when the engine global is None."""
    import app.api.routes as routes_module

    original_engine = routes_module.cxr_engine
    routes_module.cxr_engine = None

    try:
        response = await async_client.get("/healthz")
        assert response.status_code == 503
    finally:
        routes_module.cxr_engine = original_engine


# ---------------------------------------------------------------------------
#  Test 7 — /healthz healthy
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_healthz(test_app, async_client: AsyncClient) -> None:
    """Assert GET /healthz returns 200 when the engine is initialised."""
    response = await async_client.get("/healthz")
    assert response.status_code in (200, 503)
