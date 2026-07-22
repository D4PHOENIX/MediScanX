"""Database extraction layer for PowerSync Two-Tiered architecture."""

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, List, Optional

import asyncpg
from asyncpg import Pool
from langchain_core.messages import AIMessage, HumanMessage

logger = logging.getLogger(__name__)


async def setup_powersync_schema(pool: Pool) -> None:
    """Idempotently create the flat chat_messages table for PowerSync."""
    query = """
    CREATE TABLE IF NOT EXISTS chat_messages (
        id UUID PRIMARY KEY,
        thread_id UUID NOT NULL,
        patient_id UUID NOT NULL,
        is_user BOOLEAN NOT NULL,
        text TEXT NOT NULL,
        citations JSONB DEFAULT '[]'::jsonb,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_chat_messages_thread_id ON chat_messages(thread_id);
    CREATE INDEX IF NOT EXISTS idx_chat_messages_patient_id ON chat_messages(patient_id);
    """
    async with pool.acquire() as conn:
        await conn.execute(query)
    logger.info("PowerSync chat_messages schema verified.")


async def _execute_with_retry(pool: Pool, query: str, records: list, max_retries: int = 3) -> None:
    """Execute a batch insert with exponential backoff on transient failures."""
    for attempt in range(max_retries):
        try:
            async with pool.acquire() as conn:
                await conn.executemany(query, records)
            return
        except (asyncpg.PostgresConnectionError, OSError) as exc:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                logger.warning(
                    "PowerSync sync attempt %d/%d failed, retrying in %ds: %s",
                    attempt + 1, max_retries, wait, exc,
                )
                await asyncio.sleep(wait)
            else:
                logger.error(
                    "PowerSync sync failed after %d attempts: %s", max_retries, exc,
                )


async def sync_state_messages(
    pool: Pool,
    thread_id: str,
    patient_id: str,
    messages: List[Any],
    citations: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Extract and upsert final messages into the chat_messages table.

    Args:
        pool: asyncpg connection pool for database operations.
        thread_id: Conversation thread identifier.
        messages: List of LangChain message objects from the graph state.
        citations: Structured citation metadata extracted from RAG tool
            results. Applied to AI-generated message records.
    """
    if not messages:
        return

    records = []
    for msg in messages:
        # 1. Safely extract the ID without skipping
        msg_id = getattr(msg, "id", None)

        # 2. Strip the LangChain prefix if it exists
        if isinstance(msg_id, str) and msg_id.startswith("lc_run--"):
            msg_id = msg_id.replace("lc_run--", "")
        
        # 3. Generate a fresh UUID if missing or empty
        if not msg_id:
            msg_id = str(uuid.uuid4())

        # 4. Append ONLY using the sanitized msg_id
        if isinstance(msg, HumanMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            records.append((msg_id, thread_id, patient_id, True, content, "[]"))

        elif isinstance(msg, AIMessage) and not msg.tool_calls:
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if content.strip():
                citations_json = json.dumps(citations) if citations else "[]"
                records.append((msg_id, thread_id, patient_id, False, content, citations_json))

    if not records:
        return

    query = """
    INSERT INTO chat_messages (id, thread_id, patient_id, is_user, text, citations, created_at)
    VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6::jsonb, NOW())
    ON CONFLICT (id) DO NOTHING
    """

    await _execute_with_retry(pool, query, records)
