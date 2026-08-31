import pytest
from httpx import Response, Request, HTTPError, TimeoutException
from unittest.mock import patch, AsyncMock, PropertyMock
from app.services.llm_service import generate_hedged_text

@pytest.fixture(autouse=True)
def mock_config():
    with patch("app.services.llm_service.gateway_config") as mock_config:
        mock_config.google_model = "gemini-3.5-flash"
        mock_config.gemini_api_key = "dummy_key"
        yield mock_config

@pytest.mark.asyncio
async def test_generate_hedged_text_success():
    mock_resp = Response(
        200,
        request=Request("POST", "url"),
        json={
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Success text."}]
                    }
                }
            ]
        }
    )
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await generate_hedged_text("test prompt")
        assert res == "Success text."

@pytest.mark.asyncio
async def test_generate_hedged_text_non_200():
    mock_resp = Response(500, request=Request("POST", "url"))
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await generate_hedged_text("test prompt")
        assert res is None

@pytest.mark.asyncio
async def test_generate_hedged_text_timeout():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = TimeoutException("timeout")
        res = await generate_hedged_text("test prompt")
        assert res is None

@pytest.mark.asyncio
async def test_generate_hedged_text_malformed_json():
    mock_resp = Response(200, request=Request("POST", "url"), content=b"invalid json")
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await generate_hedged_text("test prompt")
        assert res is None

@pytest.mark.asyncio
async def test_generate_hedged_text_empty_candidates():
    mock_resp = Response(200, request=Request("POST", "url"), json={"candidates": []})
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await generate_hedged_text("test prompt")
        assert res is None

@pytest.mark.asyncio
async def test_generate_hedged_text_empty_exception_logs_type(caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = TimeoutException("")
            res = await generate_hedged_text("test prompt")
            assert res is None
            assert "generate_hedged_text TimeoutException: (no detail)" in caplog.text

@pytest.mark.asyncio
async def test_generate_hedged_text_timeout_argument():
    # We patch AsyncClient at the class level to inspect its constructor arguments
    with patch("app.services.llm_service.AsyncClient") as MockClient:
        # Set up the mock context manager to yield a client with a mock post method
        mock_instance = MockClient.return_value
        mock_instance.__aenter__.return_value = mock_instance
        mock_post = AsyncMock()
        mock_post.return_value = Response(200, request=Request("POST", "url"), json={
            "candidates": [{"content": {"parts": [{"text": "Success"}]}}]
        })
        mock_instance.post = mock_post

        # Default timeout
        await generate_hedged_text("test prompt")
        assert MockClient.call_args[1]["timeout"].read == 8.0

        # Custom timeout
        await generate_hedged_text("test prompt", timeout=25.0)
        assert MockClient.call_args[1]["timeout"].read == 25.0
