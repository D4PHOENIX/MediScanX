import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_healthz(async_client: AsyncClient) -> None:
    """Liveness probe must return 200 and status ok."""
    response = await async_client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_ready(async_client: AsyncClient) -> None:
    """Readiness probe must return 200."""
    response = await async_client.get("/ready")
    assert response.status_code == 200
