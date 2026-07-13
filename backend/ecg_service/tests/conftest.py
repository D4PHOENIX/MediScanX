"""Test configuration and fixtures for ecg_service.

Patches the ECG engine initialisation chain so that no real ONNX session,
PyTorch checkpoint, or hardware dependency is required during CI runs.

Typical usage
-------------

    cd ecg_service && uv run pytest tests/ -v
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
# Environment defaults — MUST match the field names in Settings
# and Settings so that pydantic-settings resolves them.
# ----------------------------------------------------------------
# Point model paths at /dev/null so that any accidental file-existence
# check returns False cleanly rather than resolving to /models/.
os.environ.setdefault("ECG_ONNX_PATH", "/dev/null/mock_ecg.onnx")
os.environ.setdefault("ECG_CKPT_PATH", "/dev/null/mock_ecg.ckpt")
os.environ.setdefault("DEVICE", "cpu")


# ----------------------------------------------------------------
# Shared mock helpers
# ----------------------------------------------------------------
def _make_mock_engine() -> MagicMock:
    """Return a fully-configured mock ECGEngine instance."""
    mock = MagicMock()
    mock.ready = True
    mock.predict = AsyncMock(return_value={
        "predictions": [
            {"label": "NORM", "class_idx": 0, "confidence": 0.94, "overlay_img": None}
        ],
        "predicted_class": "NORM",
        "predicted_confidence": 0.94,
        "gradcam_overlay": None,
        "inference_time_ms": 8.5,
        "patient_id": "test_record",
    })
    return mock


# ----------------------------------------------------------------
# Application fixture
# ----------------------------------------------------------------
@pytest.fixture(scope="session")
async def test_app():
    """Yield the FastAPI application with all heavy loading patched.

    ``ECGEngine`` is replaced with a mock so that no ONNX session,
    PyTorch checkpoint, or model weights are loaded during the test run.
    The fixture drives the full FastAPI lifespan (startup + shutdown)
    via ``lifespan_context`` so the engine readiness guard works correctly.
    """
    mock_engine = _make_mock_engine()
    mock_checkpointer = MagicMock()

    async def _fake_initialize(self):
        """Stub initialize — marks engine ready without loading weights."""
        self.ready = True
        self._onnx_session = MagicMock()
        self._diagnostic_engine = MagicMock()

    with patch("app.engine.ecg_engine.ECGEngine.initialize", _fake_initialize), \
         patch("app.engine.ecg_engine.ECGEngine._load", MagicMock()):
        from app.main import app

        # Drive the lifespan context so ecg_engine global is populated.
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