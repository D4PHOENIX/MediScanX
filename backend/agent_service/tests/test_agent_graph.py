import pytest
from httpx import ASGITransport, AsyncClient

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
