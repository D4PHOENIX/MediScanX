"""LangGraph execution graph for the clinical reasoning engine."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import asyncpg
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from app.agent.powersync import setup_powersync_schema, sync_state_messages
from app.agent.state import AgentState
from app.agent.tools.fusion import fuse_multimodal_findings, orchestrate_fusion
from app.agent.tools.ml_tools import (
    run_cxr_inference,
    run_ecg_inference,
    run_skin_inference,
)
from app.agent.tools.rag_tool import search_clinical_guidelines
from app.agent.tools.temporal import (
    list_recent_scans,
    calculate_temporal_progression,
    query_patient_metrics,
)

logger = logging.getLogger(__name__)

# 
#  System Prompt — MediScanX Clinical AI Persona
# 
SYSTEM_PROMPT = """\
You are the **MediScanX Clinical AI**, a specialised medical reasoning \
assistant embedded in the MediScanX diagnostic platform.

## Identity & Tone
- You are a board-certified–level medical knowledge system.
- Maintain a **clinical, empathetic, and highly professional** tone at all times.
- When addressing clinicians, use precise medical terminology.
- When addressing patients (if indicated), use clear, accessible language.

## Operational Hierarchy (follow strictly)
1. **Search First**: For any medical, clinical, or diagnostic query, \
   ALWAYS invoke `search_clinical_guidelines` first to ground your \
   answer in the hospital's own clinical knowledge base.
2. **Synthesise Retrieved Data**: If the tool returns highly relevant \
   guidelines, synthesise them clearly. Cite the document titles \
   when referencing specific guidelines.
3. **Fallback to Internal Knowledge**: If the tool returns limited, \
   irrelevant, or no results, you MUST still provide a thorough, \
   accurate answer using your extensive internal medical training. \
   When doing so, prepend the following disclaimer to your response:

   > ⚠️ *The following information is based on general medical \
   > knowledge and was not found in the hospital's clinical \
   > guidelines database. Always verify with institutional \
   > protocols before clinical application.*

4. **Never Refuse a Medical Question**: You must always attempt to \
   answer medical questions. "I don't know" is not acceptable; \
   provide your best medical knowledge with appropriate caveats.

## Tool Usage Guidelines
- `search_clinical_guidelines` — Use for any medical knowledge query.
- `run_multimodal_fusion` — Use when asked to combine/compare results from different modalities.
- `list_recent_scans` — Use to retrieve a list of the patient's recent scans and their identifiers.
- `calculate_temporal_progression` — Use to compute progression between diagnostic results of two scans of the same modality.
- `query_patient_metrics` — Use to retrieve profile information for a patient.

## Safety & Compliance
- Never diagnose definitively. Frame outputs as "findings suggestive of" \
  or "consistent with".
- Always recommend clinical correlation and specialist consultation \
  for critical findings.
- If a critical alert is raised (risk score ≥ 0.85), clearly flag it \
  as **CRITICAL** and recommend immediate clinical review.
- If a diagnosis label is missing, empty, or a temporal trend direction is "indeterminate", say so plainly rather than inferring a conclusion from incomplete data. Never present a guess as a finding. It is better to tell the user that a result is unavailable or unclear than to describe it as though it were established.
"""

# 
#  Tools registry
# 
TOOLS: List[BaseTool] = [
    run_cxr_inference,
    run_ecg_inference,
    run_skin_inference,
    search_clinical_guidelines,
    list_recent_scans,
    calculate_temporal_progression,
    query_patient_metrics,
    fuse_multimodal_findings,
    orchestrate_fusion,
]


def _extract_citations_from_messages(messages: List[Any]) -> List[Dict[str, Any]]:
    """Scan tool-result messages for RAG citation metadata.

    Parses ToolMessage content produced by the ``search_clinical_guidelines``
    tool to extract structured citation entries (document ID, title,
    similarity score).
    """
    from langchain_core.messages import ToolMessage
    import json as _json

    citations: list[Dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        if msg.name != "search_clinical_guidelines":
            continue
        # The RAG tool returns a JSON string with citation data
        try:
            parsed = _json.loads(msg.content)
            if isinstance(parsed, list):
                for entry in parsed:
                    if isinstance(entry, dict) and "id" in entry:
                        citations.append({
                            "document_id": str(entry.get("id", "")),
                            "title": entry.get("title", ""),
                            "content_excerpt": entry.get("content", "")[:200],
                            "similarity_score": float(entry.get("similarity", 0.0)),
                        })
        except (ValueError, TypeError):
            # Content is not JSON (legacy format or error message) — skip
            continue
    return citations


# 
#  Graph nodes
# 
def _should_continue(state: AgentState) -> str:
    """Route to the tool node if the last message contains tool calls.

    Args:
        state (AgentState): The current state of the LangGraph execution.

    Returns:
        str: "tools" if there are tool calls to execute, otherwise "sync_powersync".
    """
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return "sync_powersync"


# 
#  Factory — called once during FastAPI lifespan startup
# 
@asynccontextmanager
async def build_graph(
    gemini_api_key: Optional[str],
    google_model: str,
    database_url: str,
    pool: asyncpg.Pool,
) -> AsyncGenerator[Tuple[Any, AsyncPostgresSaver], None]:
    """Build and compile the LangGraph workflow with a Postgres checkpointer.

    This coroutine must be used as an async context manager inside the FastAPI
    ``lifespan`` context so that the DB connection pool stays alive, and
    ``AsyncPostgresSaver.setup()`` runs before the first request is served.

    The system prompt is injected as the first message in every new
    conversation.  On subsequent turns the checkpointer restores the full
    message history (which already contains the ``SystemMessage``), so no
    duplication occurs.

    Args:
        gemini_api_key (Optional[str]): Google Gemini API key.
        google_model (str): Gemini model identifier (e.g. ``"gemini-2.5-flash"``).
        database_url (str): PostgreSQL DSN used for the checkpoint saver.

    Yields:
        Tuple[Any, AsyncPostgresSaver]: A tuple of ``(compiled_graph, checkpointer)`` where the compiled graph
        is ready to serve requests and the checkpointer owns the DB connection pool.
    """
    # LLM
    llm = ChatGoogleGenerativeAI(
        model=google_model,
        api_key=gemini_api_key,
        temperature=0,
        streaming=True,
    )
    model_with_tools = llm.bind_tools(TOOLS)

    # Checkpointer
    # AsyncPostgresSaver maps to the checkpoints / checkpoint_blobs /
    # checkpoint_writes tables defined in schema/0001_initial_schema.sql.
    import psycopg_pool

    await setup_powersync_schema(pool)
        
    async with psycopg_pool.AsyncConnectionPool(conninfo=database_url, min_size=2, max_size=4) as pg_pool:
        checkpointer = AsyncPostgresSaver(pg_pool)
        await checkpointer.setup()
        logger.info("AsyncPostgresSaver initialised and schema verified.")

        # Graph definition
        builder = StateGraph(AgentState)

        async def _call_model_bound(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
            """Invoke the LLM, injecting the system prompt on the first turn.

            On the first turn of a new conversation the checkpoint-restored
            message list is empty, so the only messages present are those
            sent by the current request.  We detect the absence of a
            ``SystemMessage`` and prepend one so the agent always operates
            under its clinical persona.

            On subsequent turns, ``AsyncPostgresSaver`` restores the full
            message history which already contains the ``SystemMessage``
            from the first turn — no duplication occurs.

            Args:
                state (AgentState): The current execution state.
                config (RunnableConfig): Runtime configuration provided by LangGraph.

            Returns:
                Dict[str, Any]: A dictionary containing the newly generated LLM response message.
            """
            messages = list(state["messages"])

            # Inject the system prompt only if it's not already present
            # (i.e. this is the first turn of a new conversation thread).
            has_system = any(isinstance(m, SystemMessage) for m in messages)
            if not has_system:
                messages.insert(0, SystemMessage(content=SYSTEM_PROMPT))

            # Dynamically inject the multimodal_metadata for this specific turn
            # so the LLM is aware of the current request's metadata payload.
            # We inject this ephemerally before the last message so it isn't persisted.
            if state.get("multimodal_metadata"):
                import json
                meta_str = json.dumps(state["multimodal_metadata"], indent=2)
                meta_content = (
                    f"SYSTEM CONTEXT FOR CURRENT TURN:\n"
                    f"The following multimodal_metadata was provided with the user's request. "
                    f"Use these URLs/IDs if you need to invoke inference tools:\n{meta_str}"
                )
                meta_msg = SystemMessage(content=meta_content)
                if messages:
                    messages.insert(-1, meta_msg)
                else:
                    messages.append(meta_msg)

            response = await model_with_tools.ainvoke(messages, config)
            return {"messages": [response]}

        builder.add_node("agent", _call_model_bound)
        builder.add_node("tools", ToolNode(TOOLS))
    
        async def _sync_powersync_node(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
            """Extract final user and AI messages and synchronise them to the PowerSync flat table.

            Parses tool call results from the message history to identify RAG
            citation metadata, then delegates persistence to the PowerSync
            data-extraction layer.
            """
            messages = state["messages"]
            thread_id = config.get("configurable", {}).get("thread_id")
            db_pool = config.get("configurable", {}).get("db_pool")
            patient_id = state.get("patient_id") or thread_id

            if thread_id and db_pool:
                # Extract citation data from tool messages in the conversation
                citations = _extract_citations_from_messages(messages)
                await sync_state_messages(db_pool, thread_id, patient_id, messages, citations)
            return {}
        
        builder.add_node("sync_powersync", _sync_powersync_node)

        builder.set_entry_point("agent")
        builder.add_conditional_edges(
            "agent",
            _should_continue,
            {"tools": "tools", "sync_powersync": "sync_powersync"},
        )
        builder.add_edge("tools", "agent")
        builder.add_edge("sync_powersync", END)

        compiled = builder.compile(checkpointer=checkpointer)
        logger.info("LangGraph workflow compiled with AsyncPostgresSaver checkpointer.")

        # Wrap the compiled graph to inject the db_pool into every run's configurable
        original_astream_events = compiled.astream_events

        async def _astream_events_with_pool(
            input_data: Any,
            *,
            version: str = "v2",
            config: Optional[RunnableConfig] = None,
            **kwargs: Any,
        ) -> AsyncGenerator[Any, None]:
            """Proxy for the compiled graph's astream_events that injects the database pool.
            
            Args:
                input_data (Any): The input payload for the graph execution.
                version (str, optional): The stream events API version. Defaults to "v2".
                config (Optional[RunnableConfig], optional): Runtime configuration provided by LangGraph. Defaults to None.
                **kwargs (Any): Additional keyword arguments.
                
            Yields:
                Any: The streamed events from the graph execution.
            """
            config = config or {}
            configurable = config.get("configurable", {})
            configurable["db_pool"] = pool
            config["configurable"] = configurable
            async for event in original_astream_events(input_data, version=version, config=config, **kwargs):
                yield event

        compiled.astream_events = _astream_events_with_pool

        yield compiled, checkpointer
