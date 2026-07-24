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
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@aws-0-eu-central-1.pooler.supabase.com:5432/test")
os.environ.setdefault("SUPABASE_URL", "http://mock-supabase")
os.environ.setdefault("SUPABASE_PUBLISHABLE_KEY", "mock-publishable-key")
os.environ.setdefault("SUPABASE_SECRET_KEY", "mock-secret-key")
os.environ.setdefault("SUPABASE_JWKS_URL", "http://mock-supabase/.well-known/jwks.json")
os.environ.setdefault("CXR_SERVICE_URL", "http://mock-cxr:8001/predict")
os.environ.setdefault("ECG_SERVICE_URL", "http://mock-ecg:8002/predict")
os.environ.setdefault("SKIN_SERVICE_URL", "http://mock-skin:8003/predict")


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
    from unittest.mock import patch

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

        with patch("app.main.asyncpg.create_pool", new_callable=AsyncMock) as mock_pool:
            mock_pool_obj = MagicMock()
            acquire_ctx = MagicMock()
            acquire_ctx.__aenter__ = AsyncMock()
            mock_conn = MagicMock()
            mock_conn.fetchval = AsyncMock(return_value=1)
            acquire_ctx.__aenter__.return_value = mock_conn
            acquire_ctx.__aexit__ = AsyncMock()
            mock_pool_obj.acquire.return_value = acquire_ctx
            mock_pool_obj.close = AsyncMock()
            mock_pool.return_value = mock_pool_obj
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

from jose import jwt
import time

PRIVATE_PEM = """\
-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQggosyvr8VSPb/UTdv
DcYJONWOmcI73Woero+DzsLUIemhRANCAAQkTVAev2FwsLvIPUB14BrxKIOfCMCI
Ma3A1Hwa5ZONwmP/zmVP7WRoRkUbCQKowh/6PXkwMXtdsWPxyTNt5rcc
-----END PRIVATE KEY-----
"""
PUBLIC_JWK = {'alg': 'ES256', 'kty': 'EC', 'crv': 'P-256', 'x': 'JE1QHr9hcLC7yD1AdeAa8SiDnwjAiDGtwNR8GuWTjcI', 'y': 'Y__OZU_tZGhGRRsJAqjCH_o9eTAxe12xY_HJM23mtxw', 'kid': 'test-kid'}

@pytest.fixture
def auth_headers():
    claims = {
        "sub": "ff46e7d4-df9c-406f-be0c-987537a1b8a3",
        "role": "authenticated",
        "aud": "authenticated",
        "iss": "https://ppwnixwhaxpsqvufdggy.supabase.co/auth/v1",
        "exp": int(time.time()) + 3600
    }
    token = jwt.encode(claims, PRIVATE_PEM, algorithm="ES256", headers={"kid": "test-kid"})
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def test_user_id(auth_headers):
    return "ff46e7d4-df9c-406f-be0c-987537a1b8a3"

@pytest.fixture(autouse=True)
def mock_jwks():
    from unittest.mock import patch
    dummy_jwks = {"keys": [PUBLIC_JWK]}
    with patch("app.core.security.get_jwks", return_value=dummy_jwks):
        yield
