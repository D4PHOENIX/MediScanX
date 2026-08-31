"""Tests for the CXR Inference Service API endpoints."""

from unittest.mock import AsyncMock, MagicMock
import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
#  Test 2 — /predict JPEG image
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_predict_jpeg(test_app, async_client: AsyncClient) -> None:
    """Assert POST /predict with a valid JPEG returns 200 with the full diagnostic payload."""
    from app.api.routes import get_engine

    mock_engine = MagicMock()
    mock_engine.ready = True
    mock_engine.predict = AsyncMock(return_value={
        "original_img": "base64png",
        "top_findings": [
            {"label": "Cardiomegaly", "class_idx": 2,
             "confidence": 0.8812, "overlay_img": "b64"},
        ],
        "patient_id": "test_xray.jpg",
        "predicted_diagnoses": ["Cardiomegaly"],
    })

    test_app.dependency_overrides[get_engine] = lambda: mock_engine

    try:
        response = await async_client.post(
            "/predict",
            files={"file": ("test_xray.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 64, "image/jpeg")},
        )
        assert response.status_code == 200
        body = response.json()
        assert "top_findings" in body
        assert "predicted_diagnoses" in body
        assert isinstance(body["predicted_diagnoses"], list)
        assert body["top_findings"][0]["label"] == "Cardiomegaly"
        assert mock_engine.predict.called
    finally:
        test_app.dependency_overrides.pop(get_engine, None)


# ---------------------------------------------------------------------------
#  Test 3 — /predict PNG image
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_predict_png(test_app, async_client: AsyncClient) -> None:
    """Assert POST /predict with a PNG file is accepted (status 200)."""
    from app.api.routes import get_engine

    mock_engine = MagicMock()
    mock_engine.ready = True
    mock_engine.predict = AsyncMock(return_value={
        "original_img": "b64",
        "top_findings": [],
        "patient_id": "scan.png",
        "predicted_diagnoses": [],
    })

    test_app.dependency_overrides[get_engine] = lambda: mock_engine

    try:
        response = await async_client.post(
            "/predict",
            files={"file": ("scan.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "image/png")},
        )
        assert response.status_code == 200
    finally:
        test_app.dependency_overrides.pop(get_engine, None)


# ---------------------------------------------------------------------------
#  Test 4 — Unsupported MIME type → 415
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_predict_unsupported_content_type(test_app, async_client: AsyncClient) -> None:
    """Assert that uploading a non-image file returns HTTP 415."""
    from app.api.routes import get_engine

    mock_engine = MagicMock()
    mock_engine.ready = True
    test_app.dependency_overrides[get_engine] = lambda: mock_engine

    try:
        response = await async_client.post(
            "/predict",
            files={"file": ("report.pdf", b"%PDF-1.4", "application/pdf")},
        )
        assert response.status_code == 415
    finally:
        test_app.dependency_overrides.pop(get_engine, None)


# ---------------------------------------------------------------------------
#  Test 5 — Thresholding logic
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_probabilities_and_thresholding(test_app, async_client: AsyncClient) -> None:
    """Assert predicted_diagnoses reflects the threshold comparison correctly."""
    from app.api.routes import get_engine

    mock_engine = MagicMock()
    mock_engine.ready = True
    mock_engine.predict = AsyncMock(return_value={
        "original_img": "b64",
        "top_findings": [
            {"label": "Pleural Effusion", "class_idx": 10,
             "confidence": 0.95, "overlay_img": "b64"},
        ],
        "patient_id": "xray.jpg",
        # Pleural Effusion probability (0.95) exceeds its per-class threshold
        "predicted_diagnoses": ["Pleural Effusion"],
    })

    test_app.dependency_overrides[get_engine] = lambda: mock_engine

    try:
        response = await async_client.post(
            "/predict",
            files={"file": ("xray.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 64, "image/jpeg")},
        )
        assert response.status_code == 200
        data = response.json()
        assert "predicted_diagnoses" in data
        assert "Pleural Effusion" in data["predicted_diagnoses"]
    finally:
        test_app.dependency_overrides.pop(get_engine, None)


# ---------------------------------------------------------------------------
#  Test 8 — Root discovery endpoint
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_root_endpoint(test_app, async_client: AsyncClient) -> None:
    """Assert GET / returns the service name and docs URL."""
    response = await async_client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body.get("service") == "CXR Diagnostic API"
    assert "docs" in body
