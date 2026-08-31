"""Tests for the Gateway API authentication barrier."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

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
