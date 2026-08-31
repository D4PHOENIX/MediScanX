"""Tests for the care relationships endpoints in the patient router.

NOT VERIFIED BY AUTOMATED SUITE:
- Patient-level data scoping
- Expiry handling for 'active' relationships
- Cross-patient revoke rejection

These properties require a live database environment with multiple accounts
and must be verified manually, as the gateway tests currently mock the
Supabase REST API and do not spin up a database container.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import Response, HTTPStatusError, Request as HTTPXRequest
from fastapi.testclient import TestClient
from fastapi import status

from app.main import app

client = TestClient(app)

@pytest.mark.asyncio
async def test_revoke_care_no_live_relationship_returns_404(auth_headers):
    """RPC stub raises 'no live relationship' -> route returns 404, not 500."""
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 400
    mock_response.json.return_value = {"message": "no live relationship"}
    
    # Create an HTTPStatusError
    request = HTTPXRequest("POST", "http://test")
    exc = HTTPStatusError("Error", request=request, response=mock_response)
    mock_client.post.side_effect = exc
    
    app.state.http_client = mock_client
    
    payload = {"relationship_id": "11111111-2222-3333-4444-555555555555"}
    
    response = client.post("/api/v1/patients/care-relationships/revoke", headers=auth_headers, json=payload)
    print(response.text)
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json() == {"detail": "no live relationship"}

@pytest.mark.asyncio
async def test_revoke_care_malformed_uuid_returns_422(auth_headers):
    """Malformed UUID in the revoke body -> 422, not 500. No stub needed."""
    payload = {"relationship_id": "not-a-uuid"}
    
    response = client.post("/api/v1/patients/care-relationships/revoke", headers=auth_headers, json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

@pytest.mark.asyncio
async def test_missing_or_invalid_bearer_token():
    """Missing or invalid bearer token -> 401 on both routes."""
    # GET
    response_get = client.get("/api/v1/patients/care-relationships")
    assert response_get.status_code == status.HTTP_401_UNAUTHORIZED
    
    # POST
    payload = {"relationship_id": "11111111-2222-3333-4444-555555555555"}
    response_post = client.post("/api/v1/patients/care-relationships/revoke", json=payload)
    assert response_post.status_code == status.HTTP_401_UNAUTHORIZED
    
    # Invalid token GET
    response_get_invalid = client.get("/api/v1/patients/care-relationships", headers={"Authorization": "Bearer invalid"})
    assert response_get_invalid.status_code == status.HTTP_401_UNAUTHORIZED

@pytest.mark.asyncio
async def test_get_response_schema_no_restricted_fields():
    """The GET response model exposes no email, phone_number, etc."""
    from app.api.patient_router import CareRelationshipItem
    
    schema = CareRelationshipItem.model_json_schema()
    properties = schema.get("properties", {})
    
    forbidden_fields = ["email", "phone_number", "license_number", "date_of_birth", "location", "username"]
    for field in forbidden_fields:
        assert field not in properties, f"Forbidden field {field} found in response schema!"

@pytest.mark.asyncio
async def test_get_zero_relationships_returns_200_empty_array(auth_headers):
    """GET with zero relationships returns 200 and an empty array, not 404."""
    mock_client = AsyncMock()
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = []
    
    mock_client.post.return_value = mock_response
    app.state.http_client = mock_client
    
    response = client.get("/api/v1/patients/care-relationships", headers=auth_headers)
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data, list), f"Expected a list, but got {type(data)} - possible route shadowing"
    assert data == []


@pytest.mark.asyncio
async def test_route_table_has_no_duplicates():
    """Verify there is exactly one GET and one POST for /care-relationships."""
    schema = app.openapi()
    
    get_count = 0
    post_count = 0
    
    for path, methods in schema.get("paths", {}).items():
        if "care-relationships" in path:
            if "get" in methods:
                get_count += 1
            if "post" in methods:
                post_count += 1
                
    assert get_count == 1, f"Expected exactly one GET route for care-relationships, found {get_count}"
    assert post_count == 1, f"Expected exactly one POST route for care-relationships, found {post_count}"
