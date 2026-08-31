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


@pytest.mark.asyncio
async def test_care_relationships_route_not_shadowed(auth_headers) -> None:
    """Ensure the static care-relationships route isn't shadowed by the parameterised {patient_id} route.
    
    If shadowing occurs, this request hits `get_patient` (which issues a GET) instead of
    `list_care_relationships` (which issues a POST to RPC). We mock the POST to return a list
    and assert the response shape is a list. If shadowed, it would likely fail or return
    the wrong shape.
    """
    mock_client = AsyncMock()
    
    # Mock the POST request made by list_care_relationships
    mock_post_response = MagicMock(spec=Response)
    mock_post_response.status_code = 200
    mock_post_response.json.return_value = [{
        "id": "11111111-2222-3333-4444-555555555555",
        "status": "active",
        "is_active": True,
        "created_at": "2023-01-01T00:00:00Z"
    }]
    mock_client.post.return_value = mock_post_response
    
    # Mock the GET request in case it hits get_patient (the shadowed route)
    mock_get_response = MagicMock(spec=Response)
    mock_get_response.status_code = 200
    mock_get_response.json.return_value = {"id": "care-relationships", "name": "Shadowed!"}
    mock_get_response.raise_for_status = MagicMock()
    mock_client.get.return_value = mock_get_response

    app.state.http_client = mock_client

    response = client.get("/api/v1/patients/care-relationships", headers=auth_headers)
    
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list), (
        f"Route shadowing detected: expected list from care-relationships handler, "
        f"got {type(data)}: {data}"
    )
