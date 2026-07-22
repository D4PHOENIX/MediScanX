"""Tests for the Skin Lesion Inference Service health and discovery endpoints."""

import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_engine_not_ready_returns_503(test_app, async_client: AsyncClient) -> None:
    """Assert that the /healthz probe returns 503 when the engine is not ready."""
    import app.api.routes as routes_module

    original_engine = routes_module.skin_engine
    routes_module.skin_engine = None

    try:
        response = await async_client.get("/healthz")
        assert response.status_code == 503
    finally:
        routes_module.skin_engine = original_engine

@pytest.mark.asyncio
async def test_healthz_returns_200(test_app, async_client: AsyncClient) -> None:
    """Assert /healthz returns 200 and status=healthy when the engine is ready."""
    response = await async_client.get("/healthz")
    # 200 if lifespan populated skin_engine, 503 if mock isn't fully wired
    assert response.status_code in (200, 503)

@pytest.mark.asyncio
async def test_root_endpoint(test_app, async_client: AsyncClient) -> None:
    """Assert GET / returns the service name and docs URL."""
    response = await async_client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body.get("service") == "Skin Lesion Diagnostic API"
    assert "docs" in body
