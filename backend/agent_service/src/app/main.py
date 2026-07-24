"""Agentic AI Orchestrator FastAPI entrypoint."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Dict

import asyncpg
from fastapi import FastAPI

from app.core.config import AgentConfig
from app.core.exceptions import ExceptionRegistry
from app.api.routes import router as chat_router
from app.api import health

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """Startup / shutdown lifecycle for the agent service.

    Initialises the LangGraph workflow with an ``AsyncPostgresSaver``
    checkpointer backed by the shared Supabase/Postgres instance.  The
    compiled graph is stored on ``application.state.graph`` so that
    request handlers can access it without relying on module-level
    singletons.

    Args:
        application (FastAPI): The running FastAPI application instance.

    Yields:
        None: Yields control back to the FastAPI event loop during application lifespan.
    """
    config = AgentConfig()
    application.state.config = config

    if not config.database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. "
            "The agent service requires a PostgreSQL connection for checkpointing."
        )

    google_model = config.google_model

    logger.info("Agent service starting — building LangGraph workflow…")

    from app.agent.graph import build_graph

    # Append statement_cache_size=0 for pgBouncer compatibility for asyncpg.
    # psycopg (used by langgraph checkpointer) does not support this parameter.
    _asyncpg_dsn = config.database_url
    if _asyncpg_dsn and "statement_cache_size" not in _asyncpg_dsn:
        _sep = "&" if "?" in _asyncpg_dsn else "?"
        _asyncpg_dsn = f"{_asyncpg_dsn}{_sep}statement_cache_size=0"

    pool = await asyncpg.create_pool(_asyncpg_dsn, min_size=2, max_size=10)
    application.state.db_pool = pool
    
    # Verify required database migrations have been applied
    async with pool.acquire() as conn:
        try:
            await conn.fetch("SELECT inference_source, storage_path FROM scan_results LIMIT 0")
            logger.info("Migration check passed: required columns present in scan_results.")
        except asyncpg.exceptions.UndefinedColumnError as e:
            logger.error("FATAL: Required database migrations are unapplied! Missing columns inference_source or storage_path in scan_results.")
            await pool.close()
            raise RuntimeError("Required database migrations are unapplied! Missing columns in scan_results.") from e

    try:
        async with build_graph(
            gemini_api_key=config.gemini_api_key,
            google_model=google_model,
            database_url=config.database_url,
            pool=pool,
        ) as (compiled_graph, checkpointer):

            application.state.graph = compiled_graph
            application.state.checkpointer = checkpointer

            logger.info("Agent service ready.")
            yield
    finally:
        await pool.close()

    # Shutdown
    logger.info("Agent service stopped.")


app = FastAPI(
    title="AI Orchestrator Agent",
    version="0.1.0",
    lifespan=lifespan,
)

# Install exception → HTTP mappers
ExceptionRegistry.register_handlers(app)

# Include the SSE streaming router
app.include_router(chat_router)
app.include_router(health.router, tags=["Health"])
