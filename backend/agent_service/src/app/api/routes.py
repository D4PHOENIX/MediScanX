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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------
_ROLE_LOOKUP = {
    "user": HumanMessage,
    "assistant": AIMessage,
    "system": SystemMessage,
    "human": HumanMessage,
    "ai": AIMessage,
}


def _to_langchain_messages(raw: List[RoleMessage]) -> List[AnyMessage]:
    """Convert serialised role/content dicts to LangChain message objects.

    Args:
        raw (List[RoleMessage]): A list of role and content dictionaries from the client payload.

    Returns:
        List[AnyMessage]: A list of instantiated LangChain message objects mapped to standard roles.
    """
    messages: List[AnyMessage] = []
    for item in raw:
        cls = _ROLE_LOOKUP.get(item.role.lower())
        if cls is None:
            # Fall back to HumanMessage for unsupported roles
            cls = HumanMessage
        messages.append(cls(content=item.content))
    return messages


def _format_sse(event: str, data: Dict[str, Any]) -> str:
    """Format a dictionary as a Server-Sent Event (SSE) string.

    Args:
        event (str): The type or name of the SSE event.
        data (Dict[str, Any]): The payload data to encode as JSON.

    Returns:
        str: The fully formatted SSE string terminating with double newlines.
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _event_generator(
    graph: Any,
    initial_state: Dict[str, Any],
    thread_id: str,
) -> AsyncGenerator[str, None]:
    """Stream LangGraph events and yield Server-Sent Event (SSE) chunks.

    Errors during streaming are caught and forwarded to the client as a
    structured ``error`` SSE event, preventing silent stream termination.

    Args:
        graph (Any): The compiled LangGraph instance.
        initial_state (Dict[str, Any]): The initial state payload containing patient and scan context.
        thread_id (str): The unique identifier for this conversation thread.

    Yields:
        str: Serialised Server-Sent Event (SSE) strings formatted for the client.
    """
    run_config = {
        "recursion_limit": 50,
        "configurable": {
            # thread_id scopes the checkpoint to this specific patient session.
            # Using patient_id ensures conversation history is isolated per user
            # and correctly maps to the (thread_id, checkpoint_id) PK in the
            # checkpoints table.
            "thread_id": thread_id,
        },
    }

    try:
        iterator = graph.astream_events(
            initial_state, version="v2", config=run_config
        ).__aiter__()
        pending_task = None

        while True:
            if pending_task is None:
                pending_task = asyncio.create_task(iterator.__anext__())

            done, pending = await asyncio.wait(
                [pending_task],
                timeout=15.0,
                return_when=asyncio.FIRST_COMPLETED
            )

            if not done:
                yield ": keepalive\n\n"
                continue

            try:
                event = pending_task.result()
                pending_task = None
            except StopAsyncIteration:
                break

            kind = event["event"]
            logger.debug("SSE event: %s", kind)
            data = event.get("data", {})

            # Map LangGraph event kinds to client-facing SSE events.
            if kind == "on_chat_model_stream":
                chunk = data.get("chunk")
                if chunk and hasattr(chunk, "content"):
                    content = chunk.content
                    text = ""
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict) and "text" in item:
                                text += item["text"]
                            elif isinstance(item, str):
                                text += item
                    if text:
                        yield _format_sse("text", {"text": text})

                # Only emit tool-call metadata when the chunk carries a
                # complete call (id is populated).  Partial streaming
                # fragments arrive without an id and must not be forwarded.
                tool_calls = getattr(chunk, "tool_calls", None) if chunk else None
                if tool_calls:
                    for tc in tool_calls:
                        tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                        if tc_id:  # complete chunk — safe to forward
                            yield _format_sse(
                                "ui_trigger",
                                {
                                    "type": "tool_call",
                                    "id": tc_id,
                                    "tool": tc.get("name") if isinstance(tc, dict) else str(tc),
                                    "args": tc.get("args", {}) if isinstance(tc, dict) else {},
                                },
                            )

            elif kind == "on_tool_end":
                output = data.get("output")
                # Detect specific downstream service results and wrap them
                if isinstance(output, dict):
                    if "findings" in output or "predictions" in output:
                        yield _format_sse(
                            "ui_trigger",
                            {
                                "type": "cxr_result" if "cxr" in str(output).lower() else "result",
                                **output,
                            },
                        )
                    elif output.get("result_type") == "pdf_generated":
                        yield _format_sse(
                            "ui_trigger",
                            {"type": "pdf_generated", "url": output.get("url", "")},
                        )

            elif kind == "on_chat_model_end":
                # Called when the model finishes its turn; reserved for future use.
                pass

    except AgentBaseException as exc:
        logger.error("Domain streaming error for thread_id=%s: %s", thread_id, exc.message)
        yield _format_sse("error", {
            "error": True,
            "type": exc.__class__.__name__,
            "message": exc.message,
            "context": exc.context,
        })
    except (psycopg.OperationalError, asyncpg.exceptions.PostgresError) as exc:
        logger.error("Database connection lost for thread_id=%s: %s", thread_id, exc)
        yield _format_sse("error", {
            "error": True,
            "type": "DatabaseConnectionError",
            "message": "Database connection lost. Please try again.",
            "context": {}
        })
    except Exception as exc:  # noqa: BLE001
        logger.exception("Graph streaming error for thread_id=%s: %s", thread_id, exc)
        yield _format_sse("error", {"error": True, "type": "UnhandledError", "message": str(exc), "context": {}})

    # Signal the stream end with a custom event.
    yield _format_sse("done", {})


@router.post("")
async def chat_endpoint(request: Request, payload: ChatRequest) -> StreamingResponse:
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

    Returns:
        StreamingResponse: An asynchronous Server-Sent Event stream emitting LangGraph outcomes.
    """
    # Guard: ensure the LangGraph workflow has been compiled during lifespan startup.
    if not hasattr(request.app.state, "graph") or request.app.state.graph is None:
        raise AgentEngineNotReadyError()

    # Resolve the compiled graph from app state (set during lifespan startup).
    graph = request.app.state.graph

    # Derive a stable, unique thread_id from patient_id.
    auth_header = request.headers.get("Authorization", "")
    is_dev = auth_header.strip() == "Bearer dev-token"

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
        _event_generator(graph, initial_state, thread_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",          # disable nginx proxy buffering
        },
    )
