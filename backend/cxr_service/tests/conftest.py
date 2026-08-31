"""Test configuration and fixtures for cxr_service.

Pre-set safe environment variables and mock the DenseNet‑121 model load
so that the FastAPI application can be instantiated without real PyTorch
weights, NumPy threshold files, or any cloud storage connections.

Typical usage
-------------

    cd cxr_service && uv run pytest tests/ -v
"""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import ASGITransport, AsyncClient

pytest_plugins = ["pytest_asyncio"]


def pytest_configure(config) -> None:
    """Force pytest-asyncio auto mode."""
    config.inicfg["asyncio_mode"] = "auto"


# ----------------------------------------------------------------
# Environment defaults — must match the field names in Settings.
# pydantic-settings resolves env vars case-insensitively, so
# CXR_WEIGHTS_PATH maps to Settings.CXR_WEIGHTS_PATH. The /dev/null/...
# paths make Path.exists() return False and avoid any real disk I/O.
# ----------------------------------------------------------------
os.environ.setdefault("CXR_WEIGHTS_PATH", "/dev/null/mock_densenet.pth")
os.environ.setdefault("CXR_THRESHOLDS_PATH", "/dev/null/mock_thresholds.npy")


# ----------------------------------------------------------------
# Shared mock helper
# ----------------------------------------------------------------
def _make_mock_engine() -> MagicMock:
    """Return a fully-configured mock CXREngine instance."""
    mock = MagicMock()
    mock.ready = True
    mock.predict = AsyncMock(return_value={
        "original_img": "base64encodedpng",
        "top_findings": [
            {
                "label": "Cardiomegaly",
                "class_idx": 2,
                "confidence": 0.8812,
                "overlay_img": "base64overlay",
            }
        ],
        "patient_id": "test_xray.jpg",
        "predicted_diagnoses": ["Cardiomegaly"],
    })
    return mock


# ----------------------------------------------------------------
# Application fixture
# ----------------------------------------------------------------
@pytest.fixture(scope="session")
async def test_app():
    """Yield the FastAPI application with all heavy loading patched.

    ``CXREngine.initialize`` and ``CXREngine._load`` are replaced with
    stubs so no DenseNet weights, threshold files, or disk I/O occur
    during the test run. The fixture drives the full FastAPI lifespan
    (startup + shutdown) so the engine readiness guard works correctly.
    """

    async def _fake_initialize(self) -> None:
        """Stub — marks engine ready without touching the filesystem."""
        self.ready = True
        self._diagnostic_engine = MagicMock()

    with patch("app.engine.cxr_engine.CXREngine.initialize", _fake_initialize), \
         patch("app.engine.cxr_engine.CXREngine._load", MagicMock()):

        from app.main import app

        async with app.router.lifespan_context(app):
            yield app


@pytest.fixture
async def async_client(test_app) -> AsyncClient:
    """Provide an httpx AsyncClient targeting the test FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client
