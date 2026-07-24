"""FastAPI application factory for the Gateway Backend.

Orchestrates the instantiation and configuration of the primary FastAPI application,
establishing Cross-Origin Resource Sharing (CORS) policies, registering domain-specific
exception handlers, and mounting isolated microservice proxy routers under a unified API prefix.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg
import httpx
from fastapi import FastAPI
from supabase import create_async_client
from fastapi.middleware.cors import CORSMiddleware

from app.api.agent_router import router as agent_router
from app.api.cxr_router import router as cxr_router
from app.api.ecg_router import router as ecg_router
from app.api.health import router as health_router
from app.api.patient_router import router as patient_router
from app.api.referral_router import router as referral_router
from app.api.skin_router import router as skin_router
from app.api.report_router import router as report_router
from app.api.sync_router import router as sync_router
from app.api.webhooks import router as webhook_router
from app.core.config import gateway_config
from app.core.exceptions import ExceptionRegistry

logger: logging.Logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manages the application lifecycle.

    Initializes essential resources during startup, such as the persistent asynchronous
    HTTP client used for downstream service proxying, and ensures graceful teardown
    of connections upon application shutdown.

    Args:
        app (FastAPI): The operational FastAPI application instance.

    Yields:
        None: Yields control back to the application event loop while running.
    """
    logger.info("Gateway backend starting up ...")

    # Guard: Validate SUPABASE_URL is present and well-formed
    from urllib.parse import urlparse
    if not gateway_config.supabase_url or not gateway_config.supabase_url.strip():
        logger.error("FATAL: SUPABASE_URL is missing or empty.")
        raise RuntimeError("SUPABASE_URL is missing or empty.")
    parsed_url = urlparse(gateway_config.supabase_url)
    if not parsed_url.scheme or not parsed_url.netloc or not parsed_url.scheme.startswith("http"):
        logger.error("FATAL: SUPABASE_URL must be a valid http/https URL.")
        raise RuntimeError("SUPABASE_URL must be a valid http/https URL.")

    # Shared async HTTP client for downstream ML-service proxying.
    app.state.http_client = httpx.AsyncClient()

    # Shared Supabase async SDK client — used by StorageService and any router
    # that needs direct Supabase API access.  Supports both legacy JWT and new
    # sb_secret_* API keys.
    app.state.supabase_client = await create_async_client(
        gateway_config.supabase_url,
        gateway_config.supabase_secret_key,
    )
    logger.info("Supabase async client initialized.")

    # asyncpg connection pool — direct Postgres writes to scan_results.
    # Pool size is strictly bounded to prevent exhausting Supabase's per-project
    # connection limit (Free Tier ≈ 20 conns; Pro ≈ 100 conns).
    # asyncpg_dsn appends statement_cache_size=0 for pgBouncer compatibility.
    dsn: str | None = gateway_config.asyncpg_dsn
    if dsn:
        app.state.db_pool = await asyncpg.create_pool(
            dsn,
            min_size=2,
            max_size=4,
            statement_cache_size=0,
        )
        logger.info("asyncpg pool initialized (min_size=2, max_size=4).")
        
        # Verify required database migrations have been applied
        async with app.state.db_pool.acquire() as conn:
            try:
                # We do a fast LIMIT 0 query that asks for the fields we know were recently added
                await conn.fetch("SELECT inference_source, storage_path FROM scan_results LIMIT 0")
                logger.info("Migration check passed: required columns present in scan_results.")
            except asyncpg.exceptions.UndefinedColumnError as e:
                logger.error("FATAL: Required database migrations are unapplied! Missing columns inference_source or storage_path in scan_results.")
                await app.state.db_pool.close()
                raise RuntimeError("Required database migrations are unapplied! Missing columns in scan_results.") from e
    else:
        app.state.db_pool = None
        logger.warning(
            "DATABASE_URL is not set — scan_results persistence is DISABLED. "
            "Set DATABASE_URL in .env to enable write-through persistence."
        )

    yield

    logger.info("Gateway backend shutting down ...")
    if app.state.db_pool:
        await app.state.db_pool.close()
        logger.info("asyncpg pool closed.")
    await app.state.http_client.aclose()


def create_app() -> FastAPI:
    """Builds and configures the centralized FastAPI application instance.

    Assembles the application layer by binding middleware, mounting exception
    handlers, and mapping modular routing endpoints to establish the API surface.

    Returns:
        FastAPI: A fully-configured instance of the FastAPI application.
    """
    application: FastAPI = FastAPI(
        title="Gateway Backend",
        version="0.1.0",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in gateway_config.allowed_origins.split(",") if origin.strip()],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    # Register global domain exception handlers
    ExceptionRegistry.register_handlers(application)

    # Mount all routers under the /api/v1 prefix
    api_prefix: str = "/api/v1"
    application.include_router(cxr_router, prefix=api_prefix)
    application.include_router(ecg_router, prefix=api_prefix)
    application.include_router(skin_router, prefix=api_prefix)
    application.include_router(agent_router, prefix=api_prefix)
    application.include_router(patient_router, prefix=api_prefix)
    application.include_router(referral_router, prefix=api_prefix)
    application.include_router(health_router, prefix=api_prefix)
    application.include_router(webhook_router, prefix=api_prefix)
    application.include_router(report_router, prefix=api_prefix)
    application.include_router(sync_router, prefix=api_prefix)

    return application


app: FastAPI = create_app()
