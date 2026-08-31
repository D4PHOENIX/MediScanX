"""Test configuration and fixtures for skin_service.

Patches the MobileNetV3‑Small model loading so that integration tests run
without real image‑classification weights, GPU hardware, or external services.

Typical usage
-------------

    cd skin_service && uv run pytest tests/ -v
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
# Environment defaults — MUST match the field names in Settings.
# pydantic-settings lower-cases env var names when loading them,
# so SKIN_WEIGHTS_PATH maps to Settings.skin_weights_path.
# ----------------------------------------------------------------
os.environ.setdefault("SKIN_WEIGHTS_PATH", "/dev/null/mock_skin.pth")
os.environ.setdefault("DEVICE", "cpu")
os.environ.setdefault("NUM_CLASSES", "7")
os.environ.setdefault("IMAGE_SIZE", "224")


# ----------------------------------------------------------------
# Shared mock helpers
# ----------------------------------------------------------------
def _make_mock_engine() -> MagicMock:
    """Return a fully-configured mock SkinEngine instance."""
    mock = MagicMock()
    mock.ready = True
    mock.predict = AsyncMock(return_value={
        "original_img": "base64encodedpng",
        "top_findings": [
            {
                "label": "Melanocytic nevi",
                "abbreviation": "nv",
                "class_idx": 4,
                "confidence": 0.9123,
                "overlay_img": "base64overlay",
            }
        ],
        "predicted_class": "Melanocytic nevi",
        "patient_id": "lesion.jpg",
    })
    return mock


# ----------------------------------------------------------------
# Application fixture
# ----------------------------------------------------------------
@pytest.fixture(scope="session")
async def test_app():
    """Yield the FastAPI application with all heavy loading patched.

    ``SkinEngine.initialize`` and ``SkinEngine._load`` are replaced with
    stubs so no ONNX session, PyTorch checkpoint, or model weights are
    loaded during the test run.  The fixture drives the full FastAPI
    lifespan (startup + shutdown) so the engine readiness guard works.
    """

    async def _fake_initialize(self) -> None:
        """Stub initialize — marks engine ready without loading weights."""
        self.ready = True
        self._diagnostic_engine = MagicMock()

    with patch("app.engine.skin_engine.SkinEngine.initialize", _fake_initialize), \
         patch("app.engine.skin_engine.SkinEngine._load", MagicMock()):

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
