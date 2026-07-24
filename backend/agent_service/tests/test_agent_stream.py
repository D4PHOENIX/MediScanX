import json
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient

async def _fake_stream_events(*args, **kwargs):
    yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="Analyzing ", tool_calls=None)}}
    yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="patient ", tool_calls=None)}}
    yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="scan.", tool_calls=None)}}


@pytest.mark.asyncio
async def test_sse_compliance(test_app, async_client, auth_headers: AsyncClient) -> None:
    """Assert that POST /chat returns a text/event-stream response whose
    payload contains correctly formatted SSE text events.
    """
    # Override the graph's astream_events to return our fake sequence
    test_app.state.graph.astream_events = _fake_stream_events

    response = await async_client.post("/chat", headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "Analyze patient 123."}],
            "patient_id": "00000000-0000-0000-0000-000000000123",
        },
    )

    assert response.status_code == 200, response.text

    # Validate SSE HTTP headers
    assert "text/event-stream" in response.headers.get("content-type", "")
    assert response.headers.get("cache-control") == "no-cache"

    # Validate SSE payload
    content = response.text
    assert "event: text" in content
    assert '"text": "Analyzing "' in content
    assert "event: done" in content


@pytest.mark.asyncio
async def test_sse_streaming_error_handling(test_app, async_client, auth_headers: AsyncClient) -> None:
    """Verify that domain exceptions during streaming yield the standard error envelope."""
    from app.core.exceptions import AgentBaseException

    async def _fake_error_stream(*args, **kwargs):
        yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="Wait ", tool_calls=None)}}
        raise AgentBaseException("Simulated error", status_code=500, context={"step": "testing"})

    test_app.state.graph.astream_events = _fake_error_stream

    response = await async_client.post("/chat", headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "Analyze"}],
            "patient_id": "00000000-0000-0000-0000-000000000eee",
        },
    )

    assert response.status_code == 200, response.text
    content = response.text

    assert '"text": "Wait "' in content
    assert "event: error" in content
    assert '"error": true' in content
    assert '"type": "AgentBaseException"' in content
    assert '"message": "Simulated error"' in content
    assert '"context": {"step": "testing"}' in content
    assert "event: done" in content


@pytest.mark.asyncio
async def test_error_envelope_format(test_app, async_client, auth_headers: AsyncClient) -> None:
    """Verify the domain exception handler returns the standard
    {error: true, type, message, context} JSON envelope.
    """
    from app.core.exceptions import AgentBaseException

    # Trigger a domain error via the SSE stream
    async def _error_stream(*args, **kwargs):
        yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="Wait ", tool_calls=None)}}
        raise AgentBaseException("Test envelope", status_code=500, context={"key": "val"})

    test_app.state.graph.astream_events = _error_stream

    response = await async_client.post("/chat", headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "test"}],
            "patient_id": "00000000-0000-0000-0000-000000000fff",
        },
    )

    # The error is caught in the SSE stream, so the HTTP response is still 200
    # but the SSE payload contains the error event
    content = response.text
    assert "event: error" in content
    # Parse the error event data
    for line in content.split("\n"):
        if line.startswith("data: ") and '"error": true' in line:
            data = json.loads(line[6:])
            assert data["error"] is True
            assert data["type"] == "AgentBaseException"
            assert data["message"] == "Test envelope"
            assert data["context"] == {"key": "val"}
            break
    else:
        pytest.fail("No error event with standard envelope found in SSE stream")
