"""Clinical guidelines retrieval-augmented generation tool.

Provides vector-similarity search over the ``rag_corpus`` table in
Supabase (pgvector) to ground the agent's responses in peer-reviewed
clinical literature (PubMed, StatPearls, radiology textbooks).
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
from app.models.schemas import SearchClinicalGuidelinesSchema
from transformers import AutoModel, AutoTokenizer, AutoModelForSequenceClassification
import torch
import torch.nn.functional as F
from langchain_core.runnables import RunnableConfig

from app.core.embedding_contract import QUERY_ENCODER_MODEL, CROSS_ENCODER_MODEL, EMBEDDING_DIM, NORMALIZE, MAX_LENGTH

logger = logging.getLogger(__name__)


def _get_config() -> 'AgentConfig':
    """Lazily instantiate the service configuration on first access."""
    from app.core.config import AgentConfig
    return AgentConfig()


# ---------------------------------------------------------------------------
#  Module-level singleton — avoids re-downloading / re-initialising the model
#  on every tool call (which adds several seconds of latency each time).
# ---------------------------------------------------------------------------
_query_tokenizer = None
_query_model = None
_cross_encoder_tokenizer = None
_cross_encoder_model = None


def _get_query_encoder():
    """Return the shared query embedding model, initialising it on first access."""
    global _query_tokenizer, _query_model
    if _query_model is None:
        logger.info(f"Initialising {QUERY_ENCODER_MODEL}…")
        _query_tokenizer = AutoTokenizer.from_pretrained(QUERY_ENCODER_MODEL)
        _query_model = AutoModel.from_pretrained(QUERY_ENCODER_MODEL)
        _query_model.eval()
    return _query_tokenizer, _query_model


def _get_cross_encoder():
    """Return the shared cross encoder model, initialising it on first access."""
    global _cross_encoder_tokenizer, _cross_encoder_model
    if _cross_encoder_model is None:
        logger.info(f"Initialising {CROSS_ENCODER_MODEL}…")
        _cross_encoder_tokenizer = AutoTokenizer.from_pretrained(CROSS_ENCODER_MODEL)
        _cross_encoder_model = AutoModelForSequenceClassification.from_pretrained(CROSS_ENCODER_MODEL)
        _cross_encoder_model.eval()
    return _cross_encoder_tokenizer, _cross_encoder_model


@tool(args_schema=SearchClinicalGuidelinesSchema)
async def search_clinical_guidelines(
    query: str,
    finding_label: Optional[str] = None,
    config: RunnableConfig = None,
) -> str:
    """Search clinical guidelines using vector similarity over pgvector.

    Embeds the query using the ``BAAI/bge-base-en-v1.5`` sentence-transformer
    model and performs a cosine-similarity search against the
    ``rag_corpus`` table in Supabase.

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
    # Step 0: Direct Glossary Match
    # ------------------------------------------------------------------
    glossary_row = None
    if finding_label:
        async def _fetch_glossary(conn: asyncpg.Connection):
            return await conn.fetchrow(
                "SELECT id, title, content, source, external_id FROM rag_corpus WHERE source='finding_glossary' AND external_id=$1 LIMIT 1",
                finding_label
            )
        try:
            if db_pool is not None:
                async with db_pool.acquire() as conn:
                    glossary_row = await _fetch_glossary(conn)
            else:
                conn = await asyncpg.connect(_get_config().database_url)
                try:
                    glossary_row = await _fetch_glossary(conn)
                finally:
                    await conn.close()
        except Exception as exc:
            logger.exception("Glossary search failed: %s", exc)

    # ------------------------------------------------------------------
    # Step 1: Embed the query (CPU-bound — offloaded to a thread pool)
    # ------------------------------------------------------------------
    def _embed(text: str) -> List[float]:
        tokenizer, model = _get_query_encoder()
        with torch.no_grad():
            encoded = tokenizer(text, truncation=True, padding=True, max_length=MAX_LENGTH, return_tensors='pt')
            outputs = model(**encoded)
            embeddings = outputs.last_hidden_state[:, 0, :]
            if NORMALIZE:
                embeddings = F.normalize(embeddings, p=2, dim=1)
            return embeddings[0].tolist()

    try:
        query_vector: List[float] = await asyncio.to_thread(_embed, query)
    except Exception as exc:
        logger.exception("Failed to embed query: %s", exc)
        return f"Error: Could not generate embedding for the query — {exc}"

    # ------------------------------------------------------------------
    # Step 2: Execute the pgvector similarity search
    # ------------------------------------------------------------------

    async def _execute_search(conn: asyncpg.Connection) -> List[asyncpg.Record]:
        vector_literal = "[" + ",".join(str(v) for v in query_vector) + "]"

        # Intentionally low threshold -- casts a wide net for recall; precision is handled by the downstream cross-encoder rerank, not by this filter.
        return await conn.fetch(
            f"SELECT id, title, content, source, external_id, metadata, similarity FROM match_rag_corpus($1::halfvec({EMBEDDING_DIM}), 0.1, 20, NULL, 'thoracic')",
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
    # Step 2.5: Rerank
    # ------------------------------------------------------------------
    if _get_config().rerank_enabled and rows:
        def _rerank(docs: List[asyncpg.Record]) -> List[asyncpg.Record]:
            tokenizer, model = _get_cross_encoder()
            pairs = [[query, doc["content"][:MAX_LENGTH]] for doc in docs]
            with torch.no_grad():
                features = tokenizer(pairs, padding=True, truncation=True, max_length=MAX_LENGTH, return_tensors="pt")
                scores = model(**features).logits.squeeze(-1)
            
            doc_scores = list(zip(docs, scores.tolist()))
            doc_scores.sort(key=lambda x: x[1], reverse=True)
            return [doc for doc, _ in doc_scores[:5]]

        try:
            rows = await asyncio.to_thread(_rerank, rows)
        except Exception as exc:
            logger.exception("Failed to rerank: %s", exc)

    # ------------------------------------------------------------------
    # Step 3: Build structured citation records
    # ------------------------------------------------------------------
    citation_records: List[Dict[str, Any]] = []
    seen_ids = set()

    if glossary_row:
        doc_id = str(glossary_row["id"])
        citation_records.append({
            "id": doc_id,
            "title": glossary_row["title"] or "Untitled",
            "content": glossary_row["content"] or "",
            "similarity": 1.0,
            "source": glossary_row.get("source"),
            "external_id": glossary_row.get("external_id"),
        })
        seen_ids.add(doc_id)

    if not rows and not glossary_row:
        return "No matching clinical guidelines found for this query."

    for row in (rows or []):
        doc_id = str(row["id"])
        if doc_id in seen_ids:
            continue
        title = row["title"] or "Untitled"
        content = row["content"] or ""
        similarity = float(row.get("similarity", 0.0))
        excerpt = content[:500] + "…" if len(content) > 500 else content

        citation_records.append({
            "id": doc_id,
            "title": title,
            "content": excerpt,
            "similarity": round(similarity, 4),
            "source": row.get("source"),
            "external_id": row.get("external_id"),
        })
        seen_ids.add(doc_id)

    return _json.dumps(citation_records)
