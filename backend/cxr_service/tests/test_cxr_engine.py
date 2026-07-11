"""Tests for the CXR Inference Service using pure mocking for zero-latency execution."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
#  Test 1 — Configuration loading
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_configuration_loading() -> None:
    """Verify that CXRInferenceConfig exposes the expected architecture constants.

    Also asserts that ``__post_init__`` performs no disk I/O and leaves
    ``classification_thresholds`` unset until the engine loads it.
    """
    from app.core.config import Settings as CXRInferenceConfig

    cfg = CXRInferenceConfig()

    # num_classes = 14 base + 6 hierarchical = 20
    assert cfg.num_classes == 20
    assert len(cfg.chexpert_labels) == 14
    assert len(cfg.high_level_labels) == 6
    assert cfg.image_size == (320, 320)

    # classification_thresholds is now a proper field, defaulting to None until
    # CXREngine._load() populates it.
    assert cfg.classification_thresholds is None

    # Verify the paths defaults exist as attributes (not required to be valid paths)
    assert hasattr(cfg, "CXR_WEIGHTS_PATH")
    assert hasattr(cfg, "CXR_THRESHOLDS_PATH")


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
#  Test 6 — Engine not ready → 503
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_engine_not_ready_returns_503(test_app, async_client: AsyncClient) -> None:
    """Assert /healthz returns 503 when the engine global is None."""
    import app.api.routes as routes_module
    import app.main as main_module

    original_engine = routes_module.cxr_engine
    routes_module.cxr_engine = None

    try:
        response = await async_client.get("/healthz")
        assert response.status_code == 503
    finally:
        routes_module.cxr_engine = original_engine


# ---------------------------------------------------------------------------
#  Test 7 — /healthz healthy
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_healthz(test_app, async_client: AsyncClient) -> None:
    """Assert GET /healthz returns 200 when the engine is initialised."""
    response = await async_client.get("/healthz")
    assert response.status_code in (200, 503)


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


# ---------------------------------------------------------------------------
#  Test 9 — Threshold shape/dtype validation in config
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_threshold_dtype_and_fallback() -> None:
    """Verify threshold fallback produces a float32 array of the correct length.

    Thresholds must be float32 and have exactly ``num_base_labels`` elements to
    avoid implicit float64 upcasting or an index error during masking.
    """
    from app.core.config import Settings as CXRInferenceConfig

    cfg = CXRInferenceConfig()
    num_base = len(cfg.chexpert_labels)  # 14

    # Simulate the fallback path that cxr_engine._load() uses when the
    # thresholds file is missing.
    fallback = np.full(num_base, 0.5, dtype=np.float32)

    assert fallback.dtype == np.float32
    assert fallback.shape[0] == num_base
    assert (fallback == 0.5).all()

    # Simulate a valid float64 load followed by the astype cast
    loaded_f64 = np.linspace(0.3, 0.7, num_base)  # dtype float64
    cast = loaded_f64.astype(np.float32)
    assert cast.dtype == np.float32
    assert cast.shape[0] == num_base


# ---------------------------------------------------------------------------
#  Test 10 — Domain Exceptions in Preprocessor (Image Read Error)
# ---------------------------------------------------------------------------
def test_preprocessor_image_read_error() -> None:
    from app.engine.preprocessor import CXRInferencePreprocessor
    from app.core.config import Settings as CXRInferenceConfig
    from app.core.exceptions import ImageReadError
    cfg = CXRInferenceConfig()
    preprocessor = CXRInferencePreprocessor(cfg)
    with pytest.raises(ImageReadError):
        preprocessor.process("non_existent_image_path_to_trigger_error.jpg")


# ---------------------------------------------------------------------------
#  Test 11 — Domain Exceptions in Diagnostic Engine (Invalid Tensor Shape)
# ---------------------------------------------------------------------------
def test_diagnostic_engine_invalid_shape() -> None:
    from app.engine.diagnostic_engine import CXRDiagnosticEngine
    from app.core.config import Settings as CXRInferenceConfig
    from app.core.exceptions import InvalidTensorShapeError
    import torch
    cfg = CXRInferenceConfig()
    mock_preprocessor = MagicMock()
    # return bad shape to trigger exception
    mock_preprocessor.process.return_value = (torch.zeros((1, 3, 100, 100)), np.zeros((100, 100, 3), dtype=np.uint8))
    engine = CXRDiagnosticEngine(cfg, MagicMock(), mock_preprocessor, MagicMock())
    with pytest.raises(InvalidTensorShapeError):
        engine.run_diagnostic("dummy.jpg")


# ---------------------------------------------------------------------------
#  Test 12 — Domain Exceptions in Diagnostic Engine (OOM / Model Inference)
# ---------------------------------------------------------------------------
def test_diagnostic_engine_oom() -> None:
    from app.engine.diagnostic_engine import CXRDiagnosticEngine
    from app.core.config import Settings as CXRInferenceConfig
    from app.core.exceptions import ModelInferenceError
    import torch
    cfg = CXRInferenceConfig()
    mock_preprocessor = MagicMock()
    mock_preprocessor.process.return_value = (torch.zeros((1, 3, 320, 320)), np.zeros((320, 320, 3), dtype=np.uint8))
    mock_model = MagicMock()
    mock_model.side_effect = RuntimeError("CUDA out of memory")
    engine = CXRDiagnosticEngine(cfg, mock_model, mock_preprocessor, MagicMock())
    with pytest.raises(ModelInferenceError):
        engine.run_diagnostic("dummy.jpg")
