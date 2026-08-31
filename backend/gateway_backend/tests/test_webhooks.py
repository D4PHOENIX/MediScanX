import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

@pytest.mark.asyncio
async def test_supabase_webhook() -> None:
    """Assert GET /api/v1/webhooks/supabase returns 200 with status == 'received'."""
    response = client.post("/api/v1/webhooks/supabase")
    assert response.status_code == 200
    assert response.json() == {"status": "received"}
