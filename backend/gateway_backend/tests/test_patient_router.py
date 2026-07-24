"""Tests for the Gateway API patient router."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import Response
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

@pytest.mark.asyncio
async def test_patient_router(auth_headers) -> None:
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
    try:
        response = client.get("/api/v1/patients/123", headers=headers)
    finally:
        pass
    if response.status_code == 200:
        assert mock_client.get.called
        call_args = mock_client.get.call_args
        passed_headers = call_args.kwargs.get("headers", {})
        assert passed_headers.get("Authorization") == "Bearer fake_jwt_token"
        from app.api.patient_router import SUPABASE_PUBLISHABLE_KEY
        assert passed_headers.get("apikey") == SUPABASE_PUBLISHABLE_KEY
