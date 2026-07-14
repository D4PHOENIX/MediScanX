import os
import tempfile
from pathlib import Path
from typing import Dict, Any, Set, Optional
from fastapi import APIRouter, File, UploadFile, Depends
from fastapi.responses import JSONResponse
from app.core.exceptions import SkinEngineNotReadyError, SkinBaseException
from app.engine.skin_engine import SkinEngine

# Global engine reference – populated during startup by main.py
skin_engine: Optional[SkinEngine] = None

router = APIRouter()

async def get_engine() -> SkinEngine:
    """Dependency injection function to retrieve the initialized SkinEngine.

    Returns:
        SkinEngine: The fully initialized skin lesion diagnostic engine.

    Raises:
        SkinEngineNotReadyError: If the engine is still loading or is otherwise unavailable.
    """
    if skin_engine is None or not skin_engine.ready:
        raise SkinEngineNotReadyError()
    return skin_engine


@router.get("/healthz", status_code=200)
async def healthz() -> Dict[str, str]:
    """Health check endpoint to verify service readiness.

    Returns:
        Dict[str, str]: A dictionary indicating the health status of the service.

    Raises:
        SkinEngineNotReadyError: If the diagnostic engine is unavailable or uninitialized.
    """
    if skin_engine is None or not skin_engine.ready:
        raise SkinEngineNotReadyError()
    return {"status": "healthy"}


@router.post("/predict")
async def predict(file: UploadFile = File(...), engine: SkinEngine = Depends(get_engine), top_k: int = 3) -> JSONResponse:
    """Accept a skin lesion image, run inference, and return diagnostic findings.
    
    Accepts an uploaded image file, processes it, and generates predictions and Grad-CAM overlays
    for the specified number of top classes.

    Args:
        file (UploadFile): The uploaded image file (JPEG or PNG format).
        engine (SkinEngine): The injected skin inference engine.
        top_k (int, optional): The number of top predictions to return. Defaults to 3.

    Returns:
        JSONResponse: A JSON response containing the top‑k findings, original image, and patient ID.

    Raises:
        SkinBaseException: If the uploaded file is not a supported image format.
    """
    # Content‑type guard
    allowed: Set[str] = {"image/jpeg", "image/png", "image/jpg"}
    if file.content_type not in allowed:
        raise SkinBaseException(status_code=415, message="Only JPEG/PNG images are supported.")

    # Persist the upload to a temporary file so OpenCV can read it
    suffix: str = Path(file.filename or "").suffix or ".jpg"
    tmp_fd: int
    tmp_path: str
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        contents: bytes = await file.read()
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(contents)

        # Delegate to the asynchronous inference wrapper.
        # Domain errors propagate through the registered exception handlers
        # and are automatically translated into safe JSON responses.
        result: Dict[str, Any] = await engine.predict(tmp_path, top_k=top_k)
        return JSONResponse(content=result)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


@router.get("/")
async def root() -> Dict[str, str]:
    """Root endpoint providing service metadata.

    Returns:
        Dict[str, str]: A dictionary containing the service name and documentation URL.
    """
    return {"service": "Skin Lesion Diagnostic API", "docs": "/docs"}
