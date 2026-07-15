"""Tests for the Agentic Orchestrator using pure mocking for ultra-fast execution."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


# ---------------------------------------------------------------------------
#  Helper: async generator that yields a fixed sequence of LangGraph events
# ---------------------------------------------------------------------------
async def _fake_stream_events(*args, **kwargs):
    yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="Analyzing ", tool_calls=None)}}
    yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="patient ", tool_calls=None)}}
    yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="scan.", tool_calls=None)}}


# ---------------------------------------------------------------------------
#  Test 1 — Graph factory receives a patched checkpointer (no DB needed)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_mock_langgraph_state(test_app) -> None:
    """Verify that build_graph is called once during lifespan and that the
    compiled graph is stored on app.state with the expected interface.

    The ``build_graph`` coroutine is replaced by a stub in conftest.py, so
    no real DB connection or LLM client is created.

    ``test_app`` is the session-scoped fixture that runs the lifespan context
    manager.  Without it, ``app.state.graph`` is never populated and the
    assertion below raises AttributeError.
    """
    # app.state.graph is set by the lifespan fixture in conftest.py
    graph = test_app.state.graph
    assert graph is not None, "app.state.graph must be set after lifespan startup"
    # The mock graph should expose astream_events
    assert hasattr(graph, "astream_events"), "graph must expose astream_events"


# ---------------------------------------------------------------------------
#  Test 2 — SSE compliance
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sse_compliance(test_app, async_client: AsyncClient) -> None:
    """Assert that POST /chat returns a text/event-stream response whose
    payload contains correctly formatted SSE text events.
    """
    # Override the graph's astream_events to return our fake sequence
    test_app.state.graph.astream_events = _fake_stream_events

    response = await async_client.post(
        "/chat",
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


# ---------------------------------------------------------------------------
#  Test 2b — SSE streaming error handling
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sse_streaming_error_handling(test_app, async_client: AsyncClient) -> None:
    """Verify that domain exceptions during streaming yield the standard error envelope."""
    from app.core.exceptions import AgentBaseException

    async def _fake_error_stream(*args, **kwargs):
        yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="Wait ", tool_calls=None)}}
        raise AgentBaseException("Simulated error", status_code=500, context={"step": "testing"})

    test_app.state.graph.astream_events = _fake_error_stream

    response = await async_client.post(
        "/chat",
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


# ---------------------------------------------------------------------------
#  Test 3 — thread_id isolation per patient
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_thread_id_isolation(test_app, async_client: AsyncClient) -> None:
    """Verify that distinct patient_ids produce distinct thread_ids in the
    LangGraph configurable dict, preventing cross-patient state bleed.
    """
    captured_configs: list = []

    async def _capture_config(initial_state, version, config):
        captured_configs.append(config)
        return
        yield  # make it an async generator

    test_app.state.graph.astream_events = _capture_config

    for patient_id in ("00000000-0000-0000-0000-00000000000a", "00000000-0000-0000-0000-00000000000b"):
        await async_client.post(
            "/chat",
            json={
                "messages": [{"role": "user", "content": "Hi"}],
                "patient_id": patient_id,
            },
        )

    assert len(captured_configs) == 2
    thread_ids = [c["configurable"]["thread_id"] for c in captured_configs]
    assert thread_ids[0] == "00000000-0000-0000-0000-00000000000a"
    assert thread_ids[1] == "00000000-0000-0000-0000-00000000000b"
    assert thread_ids[0] != thread_ids[1], "Different patients must have different thread_ids"


# ---------------------------------------------------------------------------
#  Test 4 — query_patient_metrics tool (mocked asyncpg)
# ---------------------------------------------------------------------------
import app.agent.tools.temporal  # Load module before patch
@pytest.mark.asyncio
@patch("app.agent.tools.temporal.asyncpg.connect", new_callable=AsyncMock)
@patch.dict("os.environ", {"DATABASE_URL": "postgresql://test:test@localhost:5432/test"})
async def test_query_patient_metrics(mock_connect: AsyncMock) -> None:
    """Test the query_patient_metrics tool returns formatted newline-separated output."""
    from app.agent.tools.temporal import query_patient_metrics

    mock_conn = AsyncMock()
    mock_connect.return_value = mock_conn

    # Mock successful fetch from patient_metrics table
    mock_conn.fetchrow.return_value = {
        "id": "row-1",
        "patient_id": "P123",
        "age": 45,
        "heart_rate": 72,
        "blood_pressure": "120/80",
        "created_at": None,
        "updated_at": None,
    }

    result = await query_patient_metrics.ainvoke({"patient_id": "P123"})

    # Verify actual newlines (not escaped \\n) are present
    assert "\n" in result, "Output must contain real newline characters, not escaped \\\\n"
    assert "Metrics for patient" in result
    assert "age: 45" in result
    assert "heart_rate: 72" in result
    assert "blood_pressure: 120/80" in result

    # Test fallback exception handling
    mock_conn.fetchrow.side_effect = Exception("DB error")
    result_error = await query_patient_metrics.ainvoke({"patient_id": "P123"})
    assert "An error occurred" in result_error


# ---------------------------------------------------------------------------
#  Test 5 — fuse_multimodal_findings (pure, no mocking needed)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_fuse_multimodal_findings_critical_alert() -> None:
    """Verify that a high ECG confidence triggers the critical alert.

    Math verification (normalized scoring):
        ECG weight = 1.5, max_prob = 0.92
        weighted_score = 0.92 × 1.5 = 1.38
        applied_weight = 1.5
        normalized = 1.38 / 1.5 = 0.92
        0.92 >= 0.85 → critical_alert = True
    """
    from app.agent.tools.fusion import fuse_multimodal_findings

    result = await fuse_multimodal_findings.ainvoke(
        {
            "ecg_results": {
                "predicted_class": "AFIB",
                "probabilities": {"AFIB": 0.92, "Normal": 0.08},
            }
        }
    )
    # ECG weight = 1.5, max_prob = 0.92 → normalized = 0.92 / 1.0 = 0.92
    assert result["critical_alert"] is True
    assert "ECG: AFIB" in result["detected_conditions"]
    # After normalization: 0.92 * 1.5 / 1.5 = 0.92
    assert result["aggregated_risk_score"] == pytest.approx(0.92, abs=1e-4)
    assert result["aggregated_risk_score"] <= 1.0, "Risk score must not exceed 1.0"


@pytest.mark.asyncio
async def test_fuse_multimodal_findings_no_alert() -> None:
    """Verify that a low-confidence skin finding does not trigger a critical alert."""
    from app.agent.tools.fusion import fuse_multimodal_findings

    result = await fuse_multimodal_findings.ainvoke(
        {
            "skin_results": {
                "predicted_class": "Benign",
                "probabilities": {"Benign": 0.50, "Malignant": 0.50},
            }
        }
    )
    # Skin weight = 1.0, max_prob = 0.50 → normalized = 0.50 / 1.0 = 0.50
    assert result["critical_alert"] is False
    assert result["aggregated_risk_score"] == pytest.approx(0.5, abs=1e-4)
    assert result["aggregated_risk_score"] <= 1.0


@pytest.mark.asyncio
async def test_fuse_multimodal_findings_multi_modality() -> None:
    """Verify normalized risk score across multiple modalities.

    Math verification:
        ECG: max_prob=0.92, weight=1.5 → weighted=1.38
        CXR: max_prob=0.80, weight=1.2 → weighted=0.96
        sum_weighted = 1.38 + 0.96 = 2.34
        sum_weights = 1.5 + 1.2 = 2.7
        normalized = 2.34 / 2.7 ≈ 0.8667
        0.8667 >= 0.85 → critical_alert = True
    """
    from app.agent.tools.fusion import fuse_multimodal_findings

    result = await fuse_multimodal_findings.ainvoke(
        {
            "ecg_results": {
                "predicted_class": "AFIB",
                "probabilities": {"AFIB": 0.92, "Normal": 0.08},
            },
            "cxr_results": {
                "predicted_class": "Cardiomegaly",
                "probabilities": {"Cardiomegaly": 0.80, "Normal": 0.20},
            },
        }
    )
    expected_score = (0.92 * 1.5 + 0.80 * 1.2) / (1.5 + 1.2)
    assert result["aggregated_risk_score"] == pytest.approx(expected_score, abs=1e-4)
    assert result["critical_alert"] is True
    assert result["aggregated_risk_score"] <= 1.0, "Normalized score must be in [0, 1]"
    assert len(result["detected_conditions"]) == 2


# ---------------------------------------------------------------------------
#  Test 5b — Risk score normalization boundary: all three modalities
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_fuse_multimodal_findings_all_modalities_bounded() -> None:
    """Verify risk score is bounded to [0.0, 1.0] when all modalities contribute.

    Even with high confidence across all modalities, normalization keeps
    the score within the probability range.
    """
    from app.agent.tools.fusion import fuse_multimodal_findings

    result = await fuse_multimodal_findings.ainvoke(
        {
            "ecg_results": {
                "predicted_class": "VT",
                "probabilities": {"VT": 0.99, "Normal": 0.01},
            },
            "cxr_results": {
                "predicted_class": "Pneumothorax",
                "probabilities": {"Pneumothorax": 0.95, "Normal": 0.05},
            },
            "skin_results": {
                "predicted_class": "Melanoma",
                "probabilities": {"Melanoma": 0.98, "Benign": 0.02},
            },
        }
    )
    # All weights: ECG=1.5, CXR=1.2, Skin=1.0 → sum=3.7
    # Weighted: 0.99*1.5 + 0.95*1.2 + 0.98*1.0 = 1.485 + 1.14 + 0.98 = 3.605
    # Normalized: 3.605 / 3.7 ≈ 0.9743
    expected = (0.99 * 1.5 + 0.95 * 1.2 + 0.98 * 1.0) / (1.5 + 1.2 + 1.0)
    assert result["aggregated_risk_score"] == pytest.approx(expected, abs=1e-4)
    assert 0.0 <= result["aggregated_risk_score"] <= 1.0
    assert result["critical_alert"] is True
    assert len(result["detected_conditions"]) == 3


# ---------------------------------------------------------------------------
#  Test 6 — Pydantic V2 schema validation
# ---------------------------------------------------------------------------
def test_schemas_validation() -> None:
    """Verify strict Pydantic V2 schemas enforce type constraints."""
    from app.models.schemas import RoleMessage, ChatRequest, Citation

    # Valid role
    msg = RoleMessage(role="user", content="Hello")
    assert msg.role == "user"

    # Invalid role must raise
    with pytest.raises(Exception):
        RoleMessage(role="invalid_role", content="test")

    # Citation bounds
    cite = Citation(
        document_id="doc-1",
        title="Test",
        content_excerpt="excerpt",
        similarity_score=0.95,
    )
    assert cite.similarity_score == 0.95

    # similarity_score out of bounds
    with pytest.raises(Exception):
        Citation(
            document_id="doc-2",
            title="Test",
            content_excerpt="excerpt",
            similarity_score=1.5,
        )


# ---------------------------------------------------------------------------
#  Test 7 — JSON error envelope alignment with monorepo standard
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_error_envelope_format(test_app, async_client: AsyncClient) -> None:
    """Verify the domain exception handler returns the standard
    {error: true, type, message, context} JSON envelope.
    """
    from app.core.exceptions import AgentBaseException

    # Trigger a domain error via the SSE stream
    async def _error_stream(*args, **kwargs):
        yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="Wait ", tool_calls=None)}}
        raise AgentBaseException("Test envelope", status_code=500, context={"key": "val"})

    test_app.state.graph.astream_events = _error_stream

    response = await async_client.post(
        "/chat",
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


# ---------------------------------------------------------------------------
#  Test 8 — AgentEngineNotReadyError guard
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_engine_not_ready_guard() -> None:
    """Verify that requests return 503 when the graph is not initialized."""
    from fastapi import FastAPI
    from app.core.exceptions import ExceptionRegistry
    from app.api.routes import router as chat_router

    # Create a bare FastAPI app with no lifespan (graph never set)
    bare_app = FastAPI()
    ExceptionRegistry.register_handlers(bare_app)
    bare_app.include_router(chat_router)

    async with AsyncClient(
        transport=ASGITransport(app=bare_app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/chat",
            json={
                "messages": [{"role": "user", "content": "test"}],
                "patient_id": "00000000-0000-0000-0000-000000000eee",
            },
        )

    assert response.status_code == 503
    body = response.json()
    assert body["error"] is True
    assert body["type"] == "AgentEngineNotReadyError"
    assert "not ready" in body["message"].lower()


# ---------------------------------------------------------------------------
#  Test 9 — health endpoints
# ---------------------------------------------------------------------------
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
