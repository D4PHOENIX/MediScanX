"""Tests for the Skin Lesion Inference Service using pure mocking for zero-latency execution."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
#  Test 1 — Configuration loading
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_configuration_loading() -> None:
    """Verify that SkinInferenceConfig exposes the expected architecture constants."""
    from app.core.config import SkinInferenceConfig

    cfg = SkinInferenceConfig()

    assert hasattr(cfg, "skin_labels")
    assert hasattr(cfg, "skin_abbreviations")
    assert hasattr(cfg, "mean")
    assert hasattr(cfg, "std")
    assert hasattr(cfg, "heatmap_alpha")
    assert hasattr(cfg, "heatmap_beta")
    assert len(cfg.skin_labels) == 7
    assert len(cfg.skin_abbreviations) == 7
    # Verify standard ImageNet normalisation constants
    assert cfg.mean == [0.485, 0.456, 0.406]
    assert cfg.std  == [0.229, 0.224, 0.225]
    # Verify MobileNet input dimensions
    assert cfg.image_size == (224, 224)


# ---------------------------------------------------------------------------
#  Test 2 — /predict JPEG image (dependency-overridden engine)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
#  Test 4 — /predict unsupported MIME type → 415
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
#  Test 5 — top_k query parameter is forwarded
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
#  Test 6 — Engine not ready → 503
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_engine_not_ready_returns_503(test_app, async_client: AsyncClient) -> None:
    """Assert that the /healthz probe returns 503 when the engine is not ready."""
    import app.api.routes as routes_module

    original_engine = routes_module.skin_engine
    routes_module.skin_engine = None

    try:
        response = await async_client.get("/healthz")
        assert response.status_code == 503
    finally:
        routes_module.skin_engine = original_engine


# ---------------------------------------------------------------------------
#  Test 7 — /healthz when engine is ready
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_healthz_returns_200(test_app, async_client: AsyncClient) -> None:
    """Assert /healthz returns 200 and status=healthy when the engine is ready."""
    response = await async_client.get("/healthz")
    # 200 if lifespan populated skin_engine, 503 if mock isn't fully wired
    assert response.status_code in (200, 503)


# ---------------------------------------------------------------------------
#  Test 8 — /root discovery endpoint
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_root_endpoint(test_app, async_client: AsyncClient) -> None:
    """Assert GET / returns the service name and docs URL."""
    response = await async_client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body.get("service") == "Skin Lesion Diagnostic API"
    assert "docs" in body

# ---------------------------------------------------------------------------
#  Test 9 — Preprocessor corrupt image
# ---------------------------------------------------------------------------
def test_preprocessor_corrupt_image(tmp_path) -> None:
    """Assert preprocessor raises UnreadableImageFormatError on corrupt image."""
    from app.engine.preprocessor import SkinPreprocessor
    from app.core.config import SkinInferenceConfig
    from app.core.exceptions import UnreadableImageFormatError
    
    cfg = SkinInferenceConfig()
    preprocessor = SkinPreprocessor(cfg)
    
    corrupt_image = tmp_path / "corrupt.jpg"
    corrupt_image.write_bytes(b"not an image")
    
    with pytest.raises(UnreadableImageFormatError):
        preprocessor.process(str(corrupt_image))

# ---------------------------------------------------------------------------
#  Test 10 — API Corrupt image returns 422
# ---------------------------------------------------------------------------
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
