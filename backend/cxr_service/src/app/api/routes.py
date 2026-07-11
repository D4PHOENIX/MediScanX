import os
import tempfile
from pathlib import Path
from typing import Dict, Any, Set, Optional
from fastapi import APIRouter, File, UploadFile, HTTPException, Depends
from fastapi.responses import JSONResponse
from app.engine.cxr_engine import CXREngine

# Global engine reference – populated during startup by main.py
cxr_engine: Optional[CXREngine] = None

router = APIRouter()

async def get_engine() -> CXREngine:
    """Dependency injection function to retrieve the initialized CXREngine.

    Returns:
        CXREngine: The fully initialized CXR diagnostic engine.

    Raises:
        HTTPException: If the engine is still loading or is otherwise unavailable.
    """
    if cxr_engine is None or not cxr_engine.ready:
        raise HTTPException(status_code=503, detail="CXR engine is still loading or unavailable.")
    return cxr_engine


@router.get("/healthz", status_code=200)
async def healthz() -> Dict[str, str]:
    """Health check endpoint to verify service readiness.

    Returns:
        Dict[str, str]: A dictionary indicating the health status of the service.

    Raises:
        HTTPException: If the diagnostic engine is unavailable or uninitialized.
    """
    if cxr_engine is None or not cxr_engine.ready:
        raise HTTPException(
            status_code=503,
            detail="CXR engine is still loading or unavailable.",
        )
    return {"status": "healthy"}

@router.post("/predict")
async def predict(file: UploadFile = File(...), engine: CXREngine = Depends(get_engine), top_k: int = 5) -> JSONResponse:
    """Accept a chest X-ray image, run inference, and return diagnostic findings.
    
    Accepts an uploaded image file, processes it, and generates predictions and Grad-CAM++ overlays
    for the specified number of top classes.

    Args:
        file (UploadFile): The uploaded image file (JPEG or PNG format).
        engine (CXREngine): The injected CXR inference engine.
        top_k (int, optional): The number of top predictions to return. Defaults to 5.

    Returns:
        JSONResponse: A JSON response containing the top‑k findings, original image, predicted diagnoses, and patient ID.

    Raises:
        HTTPException: If the uploaded file is not a supported image format.
    """
    # Content‑type guard
    allowed: Set[str] = {"image/jpeg", "image/png", "image/jpg"}
    if file.content_type not in allowed:
        raise HTTPException(status_code=415, detail="Only JPEG/PNG images are supported.")

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
    return {"service": "CXR Diagnostic API", "docs": "/docs"}
