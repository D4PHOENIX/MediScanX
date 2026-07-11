"""FastAPI entrypoint for the CXR diagnostic microservice."""

import asyncio
import logging
import os
import tempfile
import torch
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Dict, Optional, Any, Set

from fastapi import FastAPI, File, UploadFile, HTTPException, Depends
from fastapi.responses import JSONResponse

from app.engine.cxr_engine import CXREngine
from app.core.config import Settings
from app.core.exceptions import (
    CXRModelNotFoundError,
    InvalidTensorShapeError,
    ModelInferenceError,
    ImageReadError,
    ExceptionRegistry,
)

from app.api import routes

logger: logging.Logger = logging.getLogger("cxr.main")

# ---------------------------------------------------------------------------
#  Port Configuration: this microservice exposes port 8001 (see Dockerfile)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manages the lifecycle of the FastAPI application.

    Initializes the CXR inference engine and loads the required model weights
    upon application startup.

    Args:
        app (FastAPI): The FastAPI application instance.

    Yields:
        None: Yields control back to the application.

    Raises:
        RuntimeError: If the CXREngine fails to initialize or the model is missing.
    """
    # startup
    logger.info("Initialising CXR inference engine …")
    try:
        cfg: Settings = Settings()
        engine_instance = CXREngine(cfg=cfg)
        await engine_instance.initialize()
        routes.cxr_engine = engine_instance
        logger.info("CXR engine loaded successfully.")
    except CXRModelNotFoundError as exc:
        logger.critical("Model not found: %s", exc)
        raise RuntimeError(str(exc)) from exc
    except Exception as exc:
        logger.critical("Failed to initialise CXREngine: %s", exc)
        raise RuntimeError("CXREngine initialization failed") from exc
    yield
    # shutdown – no special teardown needed

app: FastAPI = FastAPI(title="CXR Diagnostic Service", version="0.2.0", lifespan=lifespan)

# Register DDD exception handlers so domain errors become clean JSON
ExceptionRegistry.register_handlers(app)

# Global engine reference – populated during startup
cxr_engine: Optional[CXREngine] = None

from app.api.routes import router as api_router
app.include_router(api_router)
