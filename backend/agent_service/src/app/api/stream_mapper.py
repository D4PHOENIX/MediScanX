import asyncio
import logging
from typing import Any, AsyncGenerator, Dict

import asyncpg
import psycopg

from app.core.exceptions import AgentBaseException
from app.utils.chat_utils import _format_sse

logger = logging.getLogger(__name__)

async def _event_generator(
    graph: Any,
    initial_state: Dict[str, Any],
    thread_id: str,
    auth_user_id: str,
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
            # Server-side identity injected here so tools can extract it securely
            "auth_user_id": auth_user_id,
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
