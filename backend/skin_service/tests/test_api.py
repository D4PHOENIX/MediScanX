"""Tests for the Skin Lesion Inference Service prediction API."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_predict_jpeg(test_app, async_client: AsyncClient) -> None:
    """Assert POST /predict with JPEG returns 200 and the full diagnostic payload."""
    from app.api.routes import get_engine

    mock_engine = MagicMock()
    mock_engine.ready = True
    mock_engine.predict = AsyncMock(return_value={
        "original_img": "base64png",
        "top_findings": [
            {"label": "Melanocytic nevi", "abbreviation": "nv",
             "class_idx": 4, "confidence": 0.9123, "overlay_img": "b64"},
        ],
        "predicted_class": "Melanocytic nevi",
        "patient_id": "lesion.jpg",
    })

    test_app.dependency_overrides[get_engine] = lambda: mock_engine

    try:
        response = await async_client.post(
            "/predict",
            files={"file": ("lesion.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 64, "image/jpeg")},
        )

        assert response.status_code == 200
        body = response.json()
        assert "top_findings" in body
        assert "predicted_class" in body
        assert body["predicted_class"] == "Melanocytic nevi"
        assert isinstance(body["top_findings"], list)

        # Verify engine.predict was called with the uploaded file's tmp path
        assert mock_engine.predict.called
        call_args = mock_engine.predict.call_args
        # First positional arg should be the tmp_path string
        assert isinstance(call_args.args[0], str)
    finally:
        test_app.dependency_overrides.pop(get_engine, None)

@pytest.mark.asyncio
async def test_predict_png(test_app, async_client: AsyncClient) -> None:
    """Assert POST /predict with a PNG file is accepted (status 200)."""
    from app.api.routes import get_engine

    mock_engine = MagicMock()
    mock_engine.ready = True
    mock_engine.predict = AsyncMock(return_value={
        "original_img": "b64",
        "top_findings": [],
        "predicted_class": "Melanoma",
        "patient_id": "scan.png",
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

@pytest.mark.asyncio
async def test_predict_top_k_forwarded(test_app, async_client: AsyncClient) -> None:
    """Assert that the top_k query parameter is correctly forwarded to engine.predict."""
    from app.api.routes import get_engine

    mock_engine = MagicMock()
    mock_engine.ready = True
    mock_engine.predict = AsyncMock(return_value={
        "original_img": "b64",
        "top_findings": [],
        "predicted_class": "Dermatofibroma",
        "patient_id": "lesion.jpg",
    })

    test_app.dependency_overrides[get_engine] = lambda: mock_engine

    try:
        response = await async_client.post(
            "/predict?top_k=5",
            files={"file": ("lesion.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 64, "image/jpeg")},
        )
        assert response.status_code == 200

        # Verify top_k=5 was passed to the engine
        call_kwargs = mock_engine.predict.call_args.kwargs
        assert call_kwargs.get("top_k") == 5
    finally:
        test_app.dependency_overrides.pop(get_engine, None)

@pytest.mark.asyncio
async def test_predict_api_corrupt_image(test_app, async_client: AsyncClient) -> None:
    """Assert POST /predict with a corrupt image returns 422 when engine raises UnreadableImageFormatError."""
    from app.api.routes import get_engine
    from app.core.exceptions import UnreadableImageFormatError

    mock_engine = MagicMock()
    mock_engine.ready = True
    mock_engine.predict = AsyncMock(side_effect=UnreadableImageFormatError(path="test.jpg"))

    test_app.dependency_overrides[get_engine] = lambda: mock_engine

    try:
        response = await async_client.post(
            "/predict",
            files={"file": ("test.jpg", b"corrupt data", "image/jpeg")},
        )
        assert response.status_code == 422
        body = response.json()
        assert body.get("error") is True
        assert body.get("type") == "UnreadableImageFormatError"
    finally:
        test_app.dependency_overrides.pop(get_engine, None)
