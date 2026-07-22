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


# ---------------------------------------------------------------------------
#  Tool schemas
# ---------------------------------------------------------------------------
class SearchClinicalGuidelinesSchema(BaseModel):
    query: str = Field(description="A natural-language query describing the clinical context.")
    finding_label: Optional[str] = Field(None, description="The detected finding label to fetch from the finding glossary")


class CalculateTemporalProgressionSchema(BaseModel):
    current_scan_id: str = Field(description="Identifier of the scan to be assessed.")
    previous_scan_id: Optional[str] = Field(default=None, description="Identifier of a specific previous scan (optional).")


class QueryPatientMetricsSchema(BaseModel):
    patient_id: str = Field(description="The unique identifier of the patient to query.")


class OrchestrateFusionSchema(BaseModel):
    patient_id: str = Field(description="Unique patient identifier.")
    selected_scan_ids: Optional[List[str]] = Field(default=None, description="Optional list of scan identifiers chosen by the user for fusion.")
