"""Server-Side-Events (SSE) streaming endpoint for the agent chat."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, AsyncGenerator, Dict, List

import asyncpg
import psycopg
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage

from app.core.exceptions import AgentBaseException, AgentEngineNotReadyError
from app.models.schemas import ChatRequest, RoleMessage  # noqa: F401
from app.utils.chat_utils import _format_sse, _to_langchain_messages

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


#  Helpers

from app.api.stream_mapper import _event_generator


from app.core.security import get_current_user
from fastapi import Depends

@router.post("")
async def chat_endpoint(
    request: Request, 
    payload: ChatRequest,
    auth_user_id: str = Depends(get_current_user),
) -> StreamingResponse:
    """Stream assistant responses and tool invocations via SSE.

    The ``thread_id`` sent to the LangGraph checkpointer is derived from
    ``patient_id``.  This maps each patient's conversation to a distinct
    row in the ``checkpoints`` table, preventing cross-patient state bleed.

    Example payload::

        {
            "messages": [{"role": "user", "content": "Analyse chest X-ray for patient 42"}],
            "patient_id": "42"
        }

    Args:
        request (Request): The incoming FastAPI HTTP request.
        payload (ChatRequest): The validated request payload containing conversation messages.
        auth_user_id (str): The verified identity of the caller.

    Returns:
        StreamingResponse: An asynchronous Server-Sent Event stream emitting LangGraph outcomes.
    """
    # Guard: ensure the LangGraph workflow has been compiled during lifespan startup.
    if not hasattr(request.app.state, "graph") or request.app.state.graph is None:
        raise AgentEngineNotReadyError()

    # Resolve the compiled graph from app state (set during lifespan startup).
    graph = request.app.state.graph

    patient_uuid = str(payload.patient_id) if payload.patient_id else ""
    current_scan_uuid = str(payload.current_scan_id) if payload.current_scan_id else ""

    # If patient_id is absent (unauthenticated / dev), fall back to a
    # one-off UUID that won't accumulate state across requests.
    thread_id = patient_uuid if patient_uuid else str(uuid.uuid4())

    messages = _to_langchain_messages(payload.messages)
    initial_state: Dict[str, Any] = {
        "messages": messages,
        "patient_id": patient_uuid,
        "current_scan_id": current_scan_uuid,
        "execution_step": payload.execution_step,
        "multimodal_metadata": payload.multimodal_metadata,
    }

    return StreamingResponse(
        _event_generator(graph, initial_state, thread_id, auth_user_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",          # disable nginx proxy buffering
        },
    )
