"""FastAPI entrypoint for the Skin Lesion diagnostic microservice."""

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

from app.engine.skin_engine import SkinEngine
from app.core.config import SkinInferenceConfig
from app.core.config import Settings
from app.core.exceptions import (
    SkinModelNotFoundError,
    InvalidImageDimensionError,
    ModelInferenceError,
    UnreadableImageFormatError,
    ExceptionRegistry,
)

from app.api import routes

logger: logging.Logger = logging.getLogger("skin.main")

# ---------------------------------------------------------------------------
#  Port Configuration: this microservice exposes port 8003 (see Dockerfile)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manages the lifecycle of the FastAPI application.

    Initializes the skin inference engine and loads the required model weights
    upon application startup.

    Args:
        app (FastAPI): The FastAPI application instance.

    Yields:
        None: Yields control back to the application.

    Raises:
        RuntimeError: If the SkinEngine fails to initialize or the model is missing.
    """
    # startup
    logger.info("Initialising Skin Lesion inference engine …")
    try:
        config_settings: Settings = Settings()
        # Build the domain dataclass expected by the internal diagnostic engine
        raw_weights_path = getattr(config_settings, "skin_weights_path", "./weights/skin_multidomain_weights.pth")
        resolved_weights_path = raw_weights_path
        if not Path(raw_weights_path).exists():
            container_path = Path("/weights") / Path(raw_weights_path).name
            if container_path.exists():
                resolved_weights_path = str(container_path)

        skin_inference_config: SkinInferenceConfig = SkinInferenceConfig(
            model_weights_path=resolved_weights_path,
            device=torch.device(getattr(config_settings, "device", "cpu")),
            image_size=(getattr(config_settings, "image_size", 224), getattr(config_settings, "image_size", 224)),
            num_classes=getattr(config_settings, "num_classes", 8),
            melanoma_triage_threshold=getattr(config_settings, "melanoma_triage_threshold", 0.20),
            enable_otsu_roi=getattr(config_settings, "enable_otsu_roi", True),
        )
        # Construct the engine with the domain configuration dataclass, which
        # will be forwarded to the internal SkinDiagnosticEngine.
        engine_instance = SkinEngine(cfg=skin_inference_config)
        await engine_instance.initialize()
        routes.skin_engine = engine_instance
        logger.info("Skin engine loaded successfully.")
    except SkinModelNotFoundError as exc:
        logger.critical("Model not found: %s", exc)
        raise RuntimeError(str(exc)) from exc
    except Exception as exc:
        logger.critical("Failed to initialise SkinEngine: %s", exc)
        raise RuntimeError("SkinEngine initialisation failed") from exc
    yield
    # shutdown – no special teardown needed

app: FastAPI = FastAPI(title="Skin Lesion Diagnostic Service", version="0.2.0", lifespan=lifespan)

# Register DDD exception handlers so domain errors become clean JSON
ExceptionRegistry.register_handlers(app)

# Global engine reference – populated during startup
skin_engine: Optional[SkinEngine] = None

from app.api.routes import router as api_router
app.include_router(api_router)
