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

    async def event_stream() -> AsyncGenerator[bytes, None]:
        async with httpx.AsyncClient() as client:
            try:
                async with client.stream(
                    "POST",
                    _TARGET_URL,
                    json=body,
                    headers={
                        "Accept": "text/event-stream",
                        "Cache-Control": "no-cache",
                        "Authorization": request.headers.get("Authorization", ""),
                    },
                    timeout=120.0,
                ) as response:
                    if response.status_code >= 400:
                        error_body = await response.aread()
                        logger.error(
                            "Agent service returned %d: %s",
                            response.status_code,
                            error_body.decode("utf-8", errors="replace")[:512],
                        )
                        yield f'event: error\ndata: {{"error": true, "message": "Agent service returned HTTP {response.status_code}"}}\n\n'.encode("utf-8")
                        return

                    async for chunk in response.aiter_bytes():
                        if chunk:
                            yield chunk
                        else:
                            yield b": keepalive\n\n"
            except Exception as exc:
                logger.error("Proxy streaming error: %s", exc)
                yield f'event: error\ndata: {{"error": true, "message": "Upstream connection failed: {str(exc)}"}}\n\n'.encode("utf-8")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
