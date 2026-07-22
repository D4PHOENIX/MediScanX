"""Tests for the ECG Inference Service using pure mocking for ultra-fast execution."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
#  Test 2 — /predict WFDB mode (dependency-overridden engine)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_predict_wfdb_mode(test_app, async_client: AsyncClient) -> None:
    """Assert that POST /predict with a .dat+.hea WFDB pair returns 200 and
    the expected diagnostic payload structure.
    """
    from app.api.routes import get_engine

    mock_engine = MagicMock()
    mock_engine.ready = True
    mock_engine.predict = AsyncMock(return_value={
        "predictions": [
            {"label": "NORM", "class_idx": 0, "confidence": 0.94, "overlay_img": None}
        ],
        "predicted_class": "NORM",
        "predicted_confidence": 0.94,
        "gradcam_overlay": None,
        "inference_time_ms": 8.5,
        "patient_id": "test_record",
    })

    test_app.dependency_overrides[get_engine] = lambda: mock_engine

    try:
        response = await async_client.post(
            "/predict",
            files=[
                ("files", ("test.dat", b"fake_dat_binary", "application/octet-stream")),
                ("files", ("test.hea", b"fake_hea_text", "text/plain")),
            ],
        )

        assert response.status_code == 200
        body = response.json()
        assert "predictions" in body
        assert isinstance(body["predictions"], list)
        assert body["predicted_class"] == "NORM"
        assert "inference_time_ms" in body

        # Verify engine was called with the correct keyword arguments
        call_kwargs = mock_engine.predict.call_args.kwargs
        assert call_kwargs.get("input_type") == "wfdb"
        assert "image_path" in call_kwargs
    finally:
        test_app.dependency_overrides.pop(get_engine, None)


# ---------------------------------------------------------------------------
#  Test 3 — /predict image mode
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_predict_image_mode(test_app, async_client: AsyncClient) -> None:
    """Assert that POST /predict with a single JPEG image uses input_type='image'."""
    from app.api.routes import get_engine

    mock_engine = MagicMock()
    mock_engine.ready = True
    mock_engine.predict = AsyncMock(return_value={
        "predictions": [{"label": "MI", "class_idx": 1, "confidence": 0.88, "overlay_img": None}],
        "predicted_class": "MI",
        "predicted_confidence": 0.88,
        "gradcam_overlay": None,
        "inference_time_ms": 14.2,
        "patient_id": "ecg.jpg",
    })

    test_app.dependency_overrides[get_engine] = lambda: mock_engine

    try:
        response = await async_client.post(
            "/predict",
            files=[
                ("files", ("ecg.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 100, "image/jpeg")),
            ],
        )

        assert response.status_code == 200
        body = response.json()
        assert body["predicted_class"] == "MI"

        call_kwargs = mock_engine.predict.call_args.kwargs
        assert call_kwargs.get("input_type") == "image"
    finally:
        test_app.dependency_overrides.pop(get_engine, None)


# ---------------------------------------------------------------------------
#  Test 4 — /predict unsupported content type returns 415
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_predict_unsupported_content_type(test_app, async_client: AsyncClient) -> None:
    """Assert that uploading a single file with an unsupported MIME type returns 415."""
    from app.api.routes import get_engine

    mock_engine = MagicMock()
    mock_engine.ready = True
    test_app.dependency_overrides[get_engine] = lambda: mock_engine

    try:
        response = await async_client.post(
            "/predict",
            files=[
                ("files", ("report.pdf", b"%PDF-1.4", "application/pdf")),
            ],
        )
        assert response.status_code == 415
    finally:
        test_app.dependency_overrides.pop(get_engine, None)


# ---------------------------------------------------------------------------
#  Test 5 — /predict wrong file count returns 400
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_predict_wrong_file_count(test_app, async_client: AsyncClient) -> None:
    """Assert that uploading three files returns 400."""
    from app.api.routes import get_engine

    mock_engine = MagicMock()
    mock_engine.ready = True
    test_app.dependency_overrides[get_engine] = lambda: mock_engine

    try:
        response = await async_client.post(
            "/predict",
            files=[
                ("files", ("a.dat", b"x", "application/octet-stream")),
                ("files", ("b.hea", b"y", "text/plain")),
                ("files", ("c.dat", b"z", "application/octet-stream")),
            ],
        )
        assert response.status_code == 400
    finally:
        test_app.dependency_overrides.pop(get_engine, None)
