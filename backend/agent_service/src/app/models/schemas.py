"""Pydantic V2 data-transfer schemas for the agent service API surface."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
#  Request models
# ---------------------------------------------------------------------------
class RoleMessage(BaseModel):
    """Single turn in a multi-turn conversation payload."""

    model_config = ConfigDict(strict=True)

    role: Literal["user", "assistant", "system", "human", "ai"]
    content: str


class ChatRequest(BaseModel):
    """Inbound payload for the SSE chat streaming endpoint."""

    messages: List[RoleMessage]
    patient_id: Optional[UUID] = None
    current_scan_id: Optional[UUID] = None
    execution_step: str = ""
    multimodal_metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
#  Citation model
# ---------------------------------------------------------------------------
class Citation(BaseModel):
    """A single retrieval citation referencing a source document."""

    model_config = ConfigDict(strict=True)

    document_id: str
    title: str
    content_excerpt: str
    similarity_score: float = Field(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
#  SSE event payloads
# ---------------------------------------------------------------------------
class ChatTextEvent(BaseModel):
    """Payload for a streamed text chunk SSE event."""

    text: str


class ChatToolCallEvent(BaseModel):
    """Payload for a tool-call SSE event forwarded to the client."""

    type: Literal["tool_call"]
    id: str
    tool: str
    args: Dict[str, Any] = Field(default_factory=dict)


class ChatErrorEvent(BaseModel):
    """Payload for an error SSE event."""

    error: Literal[True] = True
    type: str
    message: str
    context: Dict[str, Any] = Field(default_factory=dict)


class ChatDoneEvent(BaseModel):
    """Payload for the terminal done SSE event."""

    pass


# ---------------------------------------------------------------------------
#  Health / readiness / root responses
# ---------------------------------------------------------------------------
class HealthResponse(BaseModel):
    """Response schema for the liveness probe endpoint."""

    status: str
    version: str


class ReadyResponse(BaseModel):
    """Response schema for the readiness probe endpoint."""

    status: str


class RootResponse(BaseModel):
    """Response schema for the root service-metadata endpoint."""

    service: str
    version: str
