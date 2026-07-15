"""Test configuration and fixtures for agent_service.

Set safe environment variables and mock heavy initialisation routines
(LangGraph AsyncPostgresSaver, asyncpg, graph factory) so that tests
do not depend on external services, databases, or model downloads.

Typical usage
-------------

    cd agent_service && uv run pytest tests/ -v

Patch strategy
--------------
``main.py`` defers the import of ``app.agent.graph`` to inside the lifespan
function body::

    from app.agent.graph import build_graph   # line 46 — local/deferred

This keeps the service importable even when heavy LangChain wheels are absent.
The downside is that ``build_graph`` never lives in ``app.main``'s global
namespace, so neither ``patch("app.main.build_graph")`` nor
``patch("app.agent.graph.build_graph")`` work via the standard getattr-walk:

- ``patch("app.main.build_graph")`` → AttributeError (name not in globals)
- ``patch("app.agent.graph.build_graph")`` → AttributeError (submodule not
  imported into app.agent.__dict__, and importing it drags in langchain_core)

Solution: inject a fake ``app.agent.graph`` module into ``sys.modules``
*before* ``app.main`` is first imported.  When the lifespan runs
``from app.agent.graph import build_graph``, Python finds the fake module in
``sys.modules`` and returns the mock ``build_graph`` from it — no
``langchain_core`` is ever touched.
"""

import sys
import types
import os

import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import ASGITransport, AsyncClient

pytest_plugins = ["pytest_asyncio"]


def pytest_configure(config) -> None:
    """Force pytest-asyncio auto mode to simplify fixture usage."""
    config.inicfg["asyncio_mode"] = "auto"


# ----------------------------------------------------------------
# Safe defaults — must be set before any application module import
# so that AgentConfig picks them up at dataclass construction time.
# ----------------------------------------------------------------
os.environ.setdefault("GEMINI_API_KEY", "dummy-gemini-key-for-testing")
os.environ.setdefault("GOOGLE_MODEL", "gemini-2.5-flash")
os.environ.setdefault("DATABASE_URL", "postgresql://mock_user:mock_pass@localhost:5432/mock_db")
os.environ.setdefault("CXR_SERVICE_URL", "http://mock-cxr:8001/predict")
os.environ.setdefault("ECG_SERVICE_URL", "http://mock-ecg:8002/predict")
os.environ.setdefault("SKIN_SERVICE_URL", "http://mock-skin:8003/predict")
os.environ.setdefault("SUPABASE_URL", "http://mock-supabase")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "mock-service-role-key")


# ----------------------------------------------------------------
# Shared mock graph
# ----------------------------------------------------------------
def _make_mock_graph():
    """Return a minimal MagicMock that looks like a compiled LangGraph."""
    graph = MagicMock()
    graph.astream_events = AsyncMock(return_value=_empty_async_gen())
    return graph


async def _empty_async_gen():
    """Async generator that yields nothing — used as a safe default."""
    return
    yield  # make it an async generator


# ----------------------------------------------------------------
# Application fixture
# ----------------------------------------------------------------
@pytest.fixture(scope="session")
async def test_app():
    """Yield the FastAPI application with all heavy side-effects patched.

    Injects a fake ``app.agent.graph`` module into ``sys.modules`` so that
    the deferred ``from app.agent.graph import build_graph`` inside
    ``main.py``'s lifespan coroutine binds to a mock instead of the real
    function.  This prevents ``langchain_core``, ``langgraph``, and
    ``asyncpg`` from being imported during the test run.
    """
    mock_graph = _make_mock_graph()
    mock_checkpointer = AsyncMock()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _fake_build_graph(*args, **kwargs):
        yield mock_graph, mock_checkpointer

    # Build a fake module object that looks like app.agent.graph
    # but contains only the symbol(s) that main.py imports from it.
    fake_graph_mod = types.ModuleType("app.agent.graph")
    fake_graph_mod.build_graph = _fake_build_graph  # type: ignore[attr-defined]

    # Inject it into sys.modules BEFORE importing app.main.
    # When lifespan runs 'from app.agent.graph import build_graph', Python
    # finds our fake module in sys.modules and uses our mock directly.
    original = sys.modules.get("app.agent.graph")
    sys.modules["app.agent.graph"] = fake_graph_mod
    try:
        from app.main import app

        async with app.router.lifespan_context(app):
            yield app
    finally:
        # Restore sys.modules to its original state so other test sessions
        # or importlib.reload() calls are not affected.
        if original is None:
            sys.modules.pop("app.agent.graph", None)
        else:
            sys.modules["app.agent.graph"] = original


@pytest.fixture
async def async_client(test_app) -> AsyncClient:
    """Return an httpx AsyncClient wired to the test FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client
