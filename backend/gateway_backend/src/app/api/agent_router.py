"""SSE streaming proxy for the LangGraph agent powered by Agentic AI Orchestrator."""

import logging
from typing import AsyncGenerator, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
import httpx

from app.core.config import gateway_config
from app.core.exceptions import UpstreamServiceError
from app.core.security import get_current_user
from app.models.schemas import ChatRequest

logger: logging.Logger = logging.getLogger(__name__)

router: APIRouter = APIRouter(prefix="/agent", tags=["Agent"])

_TARGET_URL: str = f"{gateway_config.agent_service_url}/chat"


@router.post("/chat")
async def chat_with_agent(
    request: Request,
    request_data: ChatRequest,
    user_id: str = Depends(get_current_user),
) -> StreamingResponse:
    """Proxies conversational interactions to the LangGraph orchestration agent.

    Establishes an asynchronous, Server-Sent Events (SSE) streaming connection
    to the upstream Agentic AI Orchestrator. This enables real-time generation
    and delivery of diagnostic insights while maintaining persistent HTTP contexts
    for the downstream consumer.

    Args:
        request (Request): The incoming FastAPI request context containing the HTTP client.
        request_data (ChatRequest): The validated request payload encapsulating the chat context.
        user_id (str): The authenticated universal identifier of the calling user.

    Returns:
        StreamingResponse: An asynchronous iterator yielding raw SSE byte chunks.
    """
    body: Dict[str, Any] = request_data.model_dump()
    
    # Scrub empty strings to None to satisfy downstream strict UUID parsing
    if body.get("patient_id") == "":
        body["patient_id"] = None
    if body.get("current_scan_id") == "":
        body["current_scan_id"] = None

    client: httpx.AsyncClient = request.app.state.http_client
    
    try:
        req = client.build_request(
            "POST",
            _TARGET_URL,
            json=body,
            headers={
                "Accept": "text/event-stream",
                "Cache-Control": "no-cache",
                "Authorization": request.headers.get("Authorization", ""),
            },
            timeout=httpx.Timeout(300.0, connect=10.0)
        )
        response = await client.send(req, stream=True)
    except httpx.RequestError as exc:
        logger.error("Proxy streaming connect error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Upstream service is unreachable."
        ) from exc

    if response.status_code >= 400:
        error_body = await response.aread()
        await response.aclose()
        logger.error(
            "Agent service returned %d: %s",
            response.status_code,
            error_body.decode("utf-8", errors="replace")[:512],
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Upstream service returned error: {response.status_code}"
        )

    async def event_stream() -> AsyncGenerator[bytes, None]:
        try:
            async for chunk in response.aiter_bytes():
                if chunk:
                    yield chunk
                else:
                    yield b": keepalive\n\n"
        except Exception as exc:
            logger.error("Proxy streaming read error: %s", exc)
            yield f'event: error\ndata: {{"error": true, "type": "UpstreamServiceError", "message": "Upstream connection failed: {str(exc)}", "context": {{"service": "agent"}}}}\n\n'.encode("utf-8")
        finally:
            await response.aclose()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
