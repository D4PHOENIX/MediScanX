"""Health-check endpoint for the Gateway Backend.

Provides standard operational status reporting to facilitate load balancer
health probes and Kubernetes liveness/readiness checks.
"""

from datetime import datetime, timezone

from fastapi import APIRouter

from app.models.schemas import HealthResponse

router: APIRouter = APIRouter(prefix="/health", tags=["Health"])

# Capture the moment the module is imported for uptime calculation
_start_time: datetime = datetime.now(timezone.utc)


@router.get("/healthz", status_code=200)
async def healthz() -> HealthResponse:
    """Provides the fundamental operational health status of the Gateway.

    Returns:
        HealthResponse: A structured payload confirming service availability
            and reporting total continuous uptime.
    """
    uptime: float = (datetime.now(timezone.utc) - _start_time).total_seconds()
    return HealthResponse(status="ok", uptime=uptime)
