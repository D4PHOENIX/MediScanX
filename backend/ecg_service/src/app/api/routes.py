import os
import tempfile
from pathlib import Path
from typing import Dict, Any, Set, Optional, List

from fastapi import APIRouter, File, UploadFile, Depends, Query, Form
from fastapi.responses import JSONResponse

from app.core.exceptions import ECGEngineNotReadyError, ECGBaseException
from app.engine.ecg_engine import ECGEngine

# Global engine reference – populated during startup by main.py
ecg_engine: Optional[ECGEngine] = None

router = APIRouter()

async def get_engine() -> ECGEngine:
    """Dependency injection function to retrieve the initialized ECGEngine.

    Returns:
        ECGEngine: The fully initialized ECG diagnostic engine.

    Raises:
        ECGEngineNotReadyError: If the engine is still loading or is otherwise unavailable.
    """
    if ecg_engine is None or not ecg_engine.ready or not ecg_engine.is_servable:
        raise ECGEngineNotReadyError()
    return ecg_engine


@router.get("/healthz", status_code=200)
async def healthz() -> Dict[str, str]:
    """Health check endpoint to verify service readiness.

    Returns:
        Dict[str, str]: A dictionary indicating the health status of the service.

    Raises:
        ECGEngineNotReadyError: If the diagnostic engine is unavailable or uninitialized.
    """
    if ecg_engine is None or not ecg_engine.ready or not ecg_engine.is_servable:
        raise ECGEngineNotReadyError()
    return {"status": "healthy"}


_IMAGE_CONTENT_TYPES: Set[str] = {"image/jpeg", "image/png", "image/jpg"}


@router.post("/predict")
async def predict(
    file: Optional[UploadFile] = File(None, description="Single ECG image file"),
    wfdb_files: Optional[List[UploadFile]] = File(None, description="Pair of .dat and .hea WFDB files"),
    top_k: int = Form(5, description="Number of top classes to return"),
    xai: bool = Query(default=False, description="Set to true to include a base64-encoded Grad-CAM overlay."),
    engine: ECGEngine = Depends(get_engine)
) -> JSONResponse:
    """Accept an ECG signal or image, run inference, and return diagnostic findings.

    Accepts an uploaded image file or WFDB records, processes them, and generates predictions and Grad-CAM overlays
    for the specified number of top classes.

    Args:
        file (Optional[UploadFile]): The uploaded image file.
        wfdb_files (Optional[List[UploadFile]]): The uploaded WFDB files.
        top_k (int): Number of top classes to return.
        xai (bool, optional): Whether to generate Grad-CAM heatmaps. Defaults to False.
        engine (ECGEngine): The injected ECG inference engine.

    Returns:
        JSONResponse: A JSON response containing the top‑k findings, patient ID, and inference time.

    Raises:
        ECGBaseException: If the uploaded file is not a supported format or incorrect file count.
    """
    result: Dict[str, Any] = {}

    if file is not None:
        content_type: str = (file.content_type or "").split(";")[0].strip().lower()

        if content_type not in _IMAGE_CONTENT_TYPES:
            raise ECGBaseException(
                status_code=415,
                message=(
                    f"Unsupported content type '{content_type}'. "
                    "Supply a single JPEG/PNG image."
                ),
            )

        suffix: str = Path(file.filename or "ecg.jpg").suffix or ".jpg"
        tmp_fd: int
        tmp_path: str
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        try:
            contents: bytes = await file.read()
            with os.fdopen(tmp_fd, "wb") as f:
                f.write(contents)

            result = await engine.predict(
                image_path=tmp_path,
                input_type="image",
                use_gradcam=xai,
                top_k=top_k,
            )
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    elif wfdb_files is not None and len(wfdb_files) == 2:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_dir_path: Path = Path(tmp_dir)
            for upload in wfdb_files:
                filename: str = upload.filename or ""
                contents = await upload.read()
                dest: Path = tmp_dir_path / Path(filename).name
                dest.write_bytes(contents)

            dat_files: List[Path] = list(tmp_dir_path.glob("*.dat"))
            if not dat_files:
                raise ECGBaseException(
                    status_code=400,
                    message=(
                        "No .dat file found in the uploaded pair. "
                        "Upload exactly one .dat and one .hea WFDB file."
                    ),
                )
            record_path: str = str(dat_files[0].with_suffix(""))

            result = await engine.predict(
                image_path=record_path,
                input_type="wfdb",
                use_gradcam=xai,
                top_k=top_k,
            )
    else:
        raise ECGBaseException(
            status_code=400,
            message=(
                "Expected 1 file (image) or 2 files (WFDB .dat + .hea). "
                f"Received invalid input."
            ),
        )

    return JSONResponse(content=result)


@router.get("/")
async def root() -> Dict[str, str]:
    """Root endpoint providing service metadata.

    Returns:
        Dict[str, str]: A dictionary containing the service name and documentation URL.
    """
    return {"service": "ECG Diagnostic API", "docs": "/docs"}
