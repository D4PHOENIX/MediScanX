"""Clinical guidelines retrieval-augmented generation tool.

Provides vector-similarity search over the ``medical_documents`` table in
Supabase (pgvector) to ground the agent's responses in institutional
clinical guidelines.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
from typing import Annotated, Any, Dict, List, Optional

import asyncpg
from asyncpg import Pool
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)


def _get_config() -> 'AgentConfig':
    """Lazily instantiate the service configuration on first access."""
    from app.core.config import AgentConfig
    return AgentConfig()


# ---------------------------------------------------------------------------
#  Module-level singleton — avoids re-downloading / re-initialising the model
#  on every tool call (which adds several seconds of latency each time).
# ---------------------------------------------------------------------------
_embeddings: HuggingFaceEmbeddings | None = None


def _get_embeddings() -> HuggingFaceEmbeddings:
    """Return the shared embedding model, initialising it on first access."""
    global _embeddings  # noqa: PLW0603
    if _embeddings is None:
        logger.info("Initialising HuggingFaceEmbeddings (BAAI/bge-base-en-v1.5)…")
        _embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-base-en-v1.5")
    return _embeddings


class SearchClinicalGuidelinesSchema(BaseModel):
    query: str = Field(description="A natural-language query describing the clinical context.")

@tool(args_schema=SearchClinicalGuidelinesSchema)
async def search_clinical_guidelines(
    query: str,
    config: RunnableConfig = None,
) -> str:
    """Search clinical guidelines using vector similarity over pgvector.

    Embeds the query using the ``BAAI/bge-base-en-v1.5`` sentence-transformer
    model and performs a cosine-similarity search against the
    ``medical_documents`` table in Supabase.

    Args:
        query (str): A natural-language query describing the clinical context
               (e.g. "pneumonia treatment guidelines").
        config (RunnableConfig): Injected LangGraph config containing the db_pool.

    Returns:
        str: A JSON-encoded list of citation records, each containing ``id``,
        ``title``, ``content`` (excerpt), and ``similarity``.  Returns a
        descriptive error message string if the search could not be completed.
    """
    db_pool = config.get("configurable", {}).get("db_pool") if config else None
    if not _get_config().database_url:
        return "Error: Database URL is not configured — cannot search guidelines."

    # ------------------------------------------------------------------
    # Step 1: Embed the query (CPU-bound — offloaded to a thread pool)
    # ------------------------------------------------------------------
    try:
        embeddings = _get_embeddings()
        query_vector: List[float] = await asyncio.to_thread(
            embeddings.embed_query, query
        )
    except Exception as exc:
        logger.exception("Failed to embed query: %s", exc)
        return f"Error: Could not generate embedding for the query — {exc}"

    # ------------------------------------------------------------------
    # Step 2: Execute the pgvector similarity search
    # ------------------------------------------------------------------

    async def _execute_search(conn: asyncpg.Connection) -> List[asyncpg.Record]:
        # Format the vector as a pgvector literal string '[x,y,z,...]'
        # and cast it explicitly in the SQL expression.
        vector_literal = "[" + ",".join(str(v) for v in query_vector) + "]"

        return await conn.fetch(
            """
            SELECT id, title, content,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM medical_documents
            ORDER BY embedding <=> $1::vector
            LIMIT 5
            """,
            vector_literal,
        )

    try:
        if db_pool is not None:
            async with db_pool.acquire() as conn:
                rows = await _execute_search(conn)
        else:
            conn = await asyncpg.connect(_get_config().database_url)
            try:
                rows = await _execute_search(conn)
            finally:
                await conn.close()
    except Exception as exc:
        logger.exception("Vector search failed: %s", exc)
        return f"Error: Clinical guidelines search failed — {exc}"

    # ------------------------------------------------------------------
    # Step 3: Build structured citation records
    # ------------------------------------------------------------------
    if not rows:
        return "No matching clinical guidelines found for this query."

    citation_records: List[Dict[str, Any]] = []
    for row in rows:
        doc_id = str(row["id"])
        title = row["title"] or "Untitled"
        content = row["content"] or ""
        similarity = float(row["similarity"])
        # Truncate long content to keep the context window manageable
        excerpt = content[:500] + "…" if len(content) > 500 else content

        citation_records.append({
            "id": doc_id,
            "title": title,
            "content": excerpt,
            "similarity": round(similarity, 4),
        })

    # Return JSON-encoded citation list — downstream nodes parse this
    # to populate the PowerSync citations column.
    return _json.dumps(citation_records)
