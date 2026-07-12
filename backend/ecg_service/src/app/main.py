"""FastAPI entrypoint for the ECG diagnostic microservice."""

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

from app.engine.ecg_engine import ECGEngine
from app.core.config import Settings
from app.core.exceptions import (
    ECGModelNotFoundError,
    ExceptionRegistry,
)

from app.api import routes

logger: logging.Logger = logging.getLogger("ecg.main")

# ---------------------------------------------------------------------------
#  Port Configuration: this microservice exposes port 8002 (see Dockerfile)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manages the lifecycle of the FastAPI application.

    Initializes the ECG inference engine and loads the required model weights
    upon application startup.

    Args:
        app (FastAPI): The FastAPI application instance.

    Yields:
        None: Yields control back to the application.

    Raises:
        RuntimeError: If the ECGEngine fails to initialize or the model is missing.
    """
    # startup
    logger.info("Initialising ECG inference engine …")
    try:
        settings: Settings = Settings()
        cfg: Settings = Settings(
            onnx_model_path=settings.ecg_onnx_path,
            pytorch_ckpt_path=settings.ecg_ckpt_path,
        )
        engine_instance = ECGEngine(cfg=cfg)
        await engine_instance.initialize()
        routes.ecg_engine = engine_instance
        logger.info("ECG engine loaded successfully.")
    except ECGModelNotFoundError as exc:
        logger.critical("Model not found: %s", exc)
        raise RuntimeError(str(exc)) from exc
    except Exception as exc:
        logger.critical("Failed to initialise ECGEngine: %s", exc)
        raise RuntimeError("ECGEngine initialisation failed") from exc
    yield
    # shutdown – no special teardown needed

app: FastAPI = FastAPI(title="ECG Diagnostic Service", version="0.2.0", lifespan=lifespan)

# Register DDD exception handlers so domain errors become clean JSON
ExceptionRegistry.register_handlers(app)

# Global engine reference – populated during startup
ecg_engine: Optional[ECGEngine] = None

from app.api.routes import router as api_router
app.include_router(api_router)
