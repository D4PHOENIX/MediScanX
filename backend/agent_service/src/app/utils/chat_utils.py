"""Utility functions for SSE and chat formatting in the agent service."""

import json
from typing import Any, Dict, List

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage

from app.models.schemas import RoleMessage

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
