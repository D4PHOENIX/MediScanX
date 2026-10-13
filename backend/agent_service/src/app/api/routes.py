"""Server-Side-Events (SSE) streaming endpoint for the agent chat."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Dict, List

import asyncpg
import psycopg
from fastapi import APIRouter, Request, HTTPException, Depends
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


async def _assert_thread_owned(pool, thread_id: str, patient_uuid: str) -> None:
    async with pool.acquire() as conn:
        not_owned = await conn.fetchval(
            """
            SELECT EXISTS (SELECT 1 FROM public.chat_messages WHERE thread_id = $1::uuid AND patient_id <> $2::uuid)
                OR EXISTS (SELECT 1 FROM auth.users          WHERE id        = $1::uuid AND id         <> $2::uuid)
            """,
            thread_id, patient_uuid
        )
        if not_owned:
            raise HTTPException(403, "thread_id not owned by caller")

@router.post("")
async def chat_endpoint(
    request: Request, 
    payload: ChatRequest,
    auth_user_id: str = Depends(get_current_user),
) -> StreamingResponse:
    """Stream assistant responses and tool invocations via SSE.

    Identity comes from the JWT (``auth_user_id``). ``thread_id`` is the
    client-supplied value, verified by ``_assert_thread_owned``, or defaults
    to the authenticated user's id when omitted.
    
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

    patient_uuid = auth_user_id
    if payload.patient_id and str(payload.patient_id) != patient_uuid:
        raise HTTPException(403, "patient_id does not match authenticated user")
        
    current_scan_uuid = str(payload.current_scan_id) if payload.current_scan_id else ""
    thread_id = str(payload.thread_id) if payload.thread_id else patient_uuid

    if payload.thread_id and str(payload.thread_id) != patient_uuid:
        await _assert_thread_owned(request.app.state.db_pool, thread_id, patient_uuid)

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
