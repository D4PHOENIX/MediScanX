import os
import tempfile
from pathlib import Path
from typing import Dict, Any, Set, Optional, List

from fastapi import APIRouter, File, UploadFile, Depends, Query
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
    if ecg_engine is None or not ecg_engine.ready:
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
    if ecg_engine is None or not ecg_engine.ready:
        raise ECGEngineNotReadyError()
    return {"status": "healthy"}


_IMAGE_CONTENT_TYPES: Set[str] = {"image/jpeg", "image/png", "image/jpg"}


@router.post("/predict")
async def predict(
    files: List[UploadFile] = File(..., description="Upload one image file OR two WFDB files (.dat + .hea)"),
    xai: bool = Query(default=False, description="Set to true to include a base64-encoded Grad-CAM overlay."),
    engine: ECGEngine = Depends(get_engine)
) -> JSONResponse:
    """Accept an ECG signal or image, run inference, and return diagnostic findings.

    Accepts an uploaded image file or WFDB records, processes them, and generates predictions and Grad-CAM overlays
    for the specified number of top classes.

    Args:
        files (List[UploadFile]): The uploaded files.
        xai (bool, optional): Whether to generate Grad-CAM heatmaps. Defaults to False.
        engine (ECGEngine): The injected ECG inference engine.

    Returns:
        JSONResponse: A JSON response containing the top‑k findings, patient ID, and inference time.

    Raises:
        ECGBaseException: If the uploaded file is not a supported format or incorrect file count.
    """
    result: Dict[str, Any] = {}

    if len(files) == 1:
        upload: UploadFile = files[0]
        content_type: str = (upload.content_type or "").split(";")[0].strip().lower()

        if content_type not in _IMAGE_CONTENT_TYPES:
            raise ECGBaseException(
                status_code=415,
                message=(
                    f"Unsupported content type '{content_type}'. "
                    "Supply a single JPEG/PNG image, "
                    "or two WFDB files (.dat + .hea)."
                ),
            )

        suffix: str = Path(upload.filename or "ecg.jpg").suffix or ".jpg"
        tmp_fd: int
        tmp_path: str
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        try:
            contents: bytes = await upload.read()
            with os.fdopen(tmp_fd, "wb") as f:
                f.write(contents)

            result = await engine.predict(
                image_path=tmp_path,
                input_type="image",
                use_gradcam=xai,
            )
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    elif len(files) == 2:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_dir_path: Path = Path(tmp_dir)
            for upload in files:
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
            )
    else:
        raise ECGBaseException(
            status_code=400,
            message=(
                "Expected 1 file (image) or 2 files (WFDB .dat + .hea). "
                f"Received {len(files)} file(s)."
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