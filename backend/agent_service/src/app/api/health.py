"""Health check endpoints."""

from fastapi import APIRouter, Request

from app.models.schemas import HealthResponse, ReadyResponse, RootResponse

router = APIRouter()


@router.get("/", status_code=200, response_model=RootResponse)
async def root(request: Request) -> RootResponse:
    """Root endpoint returning service metadata.

    Returns:
        Dict[str, str]: A dictionary containing the service name and its current version.
    """
    return {"service": "agent_service", "version": request.app.version}


@router.get("/healthz", status_code=200, response_model=HealthResponse)
async def healthz(request: Request) -> HealthResponse:
    """Liveness probe verifying that the worker process is running.

    Returns:
        Dict[str, str]: A dictionary indicating system health status and version.
    """
    return {
        "status": "ok",
        "version": request.app.version,
    }


@router.get("/ready", response_model=ReadyResponse)
async def ready() -> ReadyResponse:
    """Readiness probe (can be extended to check downstream deps).

    Returns:
        Dict[str, str]: A dictionary indicating whether the service is ready.
    """
    return {"status": "ready"}
