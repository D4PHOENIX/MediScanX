import pytest
from httpx import AsyncClient, ASGITransport

@pytest.mark.asyncio
async def test_assetlinks_json_valid(test_app):
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.get("/.well-known/assetlinks.json")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"
        
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        
        entry = data[0]
        assert "relation" in entry
        assert "delegate_permission/common.handle_all_urls" in entry["relation"]
        assert "target" in entry
        assert entry["target"]["namespace"] == "android_app"
        assert entry["target"]["package_name"] == "com.example.mediscanx"
        assert "CA:8F:29:BB:52:9F:C5:B4:80:7E:EB:42:E5:0E:C1:EE:2F:A1:50:4E:2A:C3:EA:BE:F4:1A:4A:DF:94:76:98:D2" in entry["target"]["sha256_cert_fingerprints"]


@pytest.mark.asyncio
async def test_assetlinks_multiple_fingerprints(test_app, monkeypatch):
    from app.core.config import gateway_config
    monkeypatch.setattr(gateway_config, "android_cert_fingerprints", "FINGERPRINT_1, FINGERPRINT_2")
    
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.get("/.well-known/assetlinks.json")
        assert response.status_code == 200
        
        data = response.json()
        assert isinstance(data, list)
        assert data[0]["target"]["sha256_cert_fingerprints"] == ["FINGERPRINT_1", "FINGERPRINT_2"]


@pytest.mark.asyncio
async def test_claim_fallback_page(test_app):
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.get("/claim")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "MediScanX Report" in response.text
        assert "Authorization" not in response.headers # Ensure no auth header is required to read response (client didn't send one)


@pytest.mark.asyncio
async def test_claim_fallback_page_ignores_token(test_app):
    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummy.signature"
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.get(f"/claim?token={token}")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        
        # Token value must not appear in the response body
        assert token not in response.text
