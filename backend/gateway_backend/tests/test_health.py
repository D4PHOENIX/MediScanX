"""Tests for the Gateway API health endpoint."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

@pytest.mark.asyncio
async def test_healthz() -> None:
    """Assert GET /api/v1/health/healthz returns 200 with status == 'ok'.

    Ensure the health endpoint is correctly mounted. 
    The router has a prefix of /health, and the endpoint path is /healthz, making the full 
    path /api/v1/health/healthz.
    """
    response = client.get("/api/v1/health/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
