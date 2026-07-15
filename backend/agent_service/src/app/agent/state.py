"""LangGraph agent state definition for the medical orchestrator."""

from typing import Any, Dict

from langgraph.graph import MessagesState
from typing_extensions import NotRequired


class AgentState(MessagesState):
    """Extended LangGraph state carrying patient context and clinical metadata.

    Inherits the ``messages`` key from ``MessagesState``, which uses
    ``Annotated[list[BaseMessage], add_messages]`` under the hood. This state
    dictates the execution flow for the medical orchestrator.

    Attributes:
        patient_id (NotRequired[str]): Unique identifier for the patient under review.
        current_scan_id (NotRequired[str]): Identifier for the primary diagnostic scan currently being processed.
        execution_step (NotRequired[str]): String indicating the current phase of the LangGraph execution pipeline.
        multimodal_metadata (NotRequired[Dict[str, Any]]): Dictionary containing supplementary multi-modality data and findings.
        rag_citations (NotRequired[list[Dict[str, Any]]]): Structured citation metadata extracted from RAG tool results during graph execution.
    """

    patient_id: NotRequired[str]
    current_scan_id: NotRequired[str]
    execution_step: NotRequired[str]
    multimodal_metadata: NotRequired[Dict[str, Any]]
    rag_citations: NotRequired[list[Dict[str, Any]]]
