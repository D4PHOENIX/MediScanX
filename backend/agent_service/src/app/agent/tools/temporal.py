"""Temporal progression tool and patient metrics retrieval.

Provides database-backed comparison for tracking disease progression over time,
and tabular patient metric retrieval for clinical context enrichment.
"""

import logging
from typing import Any, Dict, List, Optional
import uuid
import json

import asyncpg
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from app.models.schemas import (
    CalculateTemporalProgressionSchema,
    QueryPatientMetricsSchema,
    ListRecentScansSchema,
)
from app.agent.tools.labels import _NORMAL_LABELS, _ABNORMAL_LABELS

logger = logging.getLogger(__name__)


def _get_config() -> 'AgentConfig':
    """Lazily instantiate the service configuration on first access."""
    from app.core.config import AgentConfig
    return AgentConfig()


@tool(args_schema=ListRecentScansSchema)
async def list_recent_scans(limit: int, config: RunnableConfig) -> str:
    """Retrieve the most recent scans belonging to the current user (patient).

    Args:
        limit (int): Maximum number of recent scans to return.
        config (RunnableConfig): Injected LangGraph config containing auth_user_id and db_pool.

    Returns:
        str: A JSON-encoded string containing a list of recent scans, or an error message.
    """
    auth_user_id = config.get("configurable", {}).get("auth_user_id")
    if not auth_user_id:
        return "Authentication error: auth_user_id not found in context."

    db_pool = config.get("configurable", {}).get("db_pool")
    
    query = """
        SELECT scan_id, modality, scan_status, scan_date, ai_diagnosis, confidence
        FROM scan_results
        WHERE user_id = $1
        ORDER BY scan_date DESC
        LIMIT $2
    """

    async def _fetch(conn: asyncpg.Connection) -> str:
        rows = await conn.fetch(query, uuid.UUID(auth_user_id), limit)
        if not rows:
            return "No recent scans found."
        
        scans = []
        for row in rows:
            scans.append({
                "scan_id": str(row["scan_id"]),
                "modality": row["modality"],
                "scan_status": row["scan_status"],
                "scan_date": row["scan_date"].isoformat() if row["scan_date"] else None,
                "ai_diagnosis": row["ai_diagnosis"],
                "confidence": float(row["confidence"]) if row["confidence"] is not None else None,
            })
        return json.dumps(scans, indent=2)

    if db_pool is not None:
        async with db_pool.acquire() as conn:
            return await _fetch(conn)
    else:
        dsn = _get_config().database_url
        if not dsn:
            return "DATABASE_URL environment variable not set."
        conn = await asyncpg.connect(dsn)
        try:
            return await _fetch(conn)
        finally:
            await conn.close()


async def _temporal_progression_impl(
    conn: asyncpg.Connection,
    auth_user_id: str,
    current_scan_id: str,
    previous_scan_id: Optional[str],
) -> Dict[str, Any]:
    """Core implementation for temporal progression computation.

    Extracted to share logic between pool-backed and standalone connection paths.

    Args:
        conn: Active asyncpg connection.
        auth_user_id: The ID of the authenticated user to enforce tenant isolation.
        current_scan_id: Identifier of the scan to be assessed.
        previous_scan_id: Identifier of a specific previous scan (optional).

    Returns:
        Dict[str, Any]: Dictionary containing progression results.
    """
    user_uuid = uuid.UUID(auth_user_id)
    
    try:
        curr_uuid = uuid.UUID(current_scan_id)
    except ValueError:
        return {"interpretation": f"Invalid current_scan_id format: '{current_scan_id}'"}

    prev_uuid = None
    if previous_scan_id is not None:
        try:
            prev_uuid = uuid.UUID(previous_scan_id)
        except ValueError:
            return {"interpretation": f"Invalid previous_scan_id format: '{previous_scan_id}'"}

    # Fetch current scan
    current = await conn.fetchrow(
        """
        SELECT scan_id, modality, ai_diagnosis, confidence, scan_date
        FROM scan_results
        WHERE scan_id = $1 AND user_id = $2
        """,
        curr_uuid, user_uuid
    )
    if current is None:
        return {
            "interpretation": f"Current scan '{current_scan_id}' not found or does not belong to the user.",
        }

    modality = current["modality"]
    if not modality:
        return {
            "interpretation": f"Current scan '{current_scan_id}' has no modality specified.",
        }
        
    current_diagnosis = current["ai_diagnosis"]
    current_conf = float(current["confidence"]) if current["confidence"] is not None else None
    current_date = current["scan_date"]

    # Retrieve previous scan
    if previous_scan_id is not None:
        prev_row = await conn.fetchrow(
            """
            SELECT scan_id, modality, ai_diagnosis, confidence, scan_date
            FROM scan_results 
            WHERE scan_id = $1 AND user_id = $2
            """, 
            prev_uuid, user_uuid
        )
        if prev_row is None:
            return {
                "interpretation": f"Previous scan '{previous_scan_id}' not found or does not belong to the user.",
            }
        if prev_row["modality"] != modality:
            return {
                "interpretation": f"Cannot compare scans of different modalities. Current is {modality}, previous is {prev_row['modality']}."
            }
    else:
        prev_row = await conn.fetchrow(
            """
            SELECT scan_id, modality, ai_diagnosis, confidence, scan_date
            FROM scan_results
            WHERE user_id = $1
              AND modality = $2
              AND scan_date < $3
              AND scan_id != $4
            ORDER BY scan_date DESC
            LIMIT 1
            """,
            user_uuid,
            modality,
            current_date,
            curr_uuid,
        )
        if prev_row is None:
            return {
                "interpretation": f"No prior scan of modality '{modality}' found for comparison.",
            }

    previous_diagnosis = prev_row["ai_diagnosis"]
    previous_conf = float(prev_row["confidence"]) if prev_row["confidence"] is not None else None
    previous_date = prev_row["scan_date"]
    
    days_between = None
    if current_date and previous_date:
        days_between = (current_date.date() - previous_date.date()).days

    confidence_delta = None
    if current_conf is not None and previous_conf is not None:
        confidence_delta = round(current_conf - previous_conf, 4)

    def get_status(label: Optional[str], mod: str) -> str:
        if not label:
            return "unknown"
        if label in _NORMAL_LABELS.get(mod, set()):
            return "normal"
        if label in _ABNORMAL_LABELS.get(mod, set()):
            return "abnormal"
        return "unknown"

    prev_status = get_status(previous_diagnosis, modality)
    curr_status = get_status(current_diagnosis, modality)

    if prev_status == "unknown" or curr_status == "unknown":
        direction = "indeterminate"
        reason = "One or both diagnoses are empty or unrecognised."
    elif prev_status == "normal" and curr_status == "abnormal":
        direction = "worsening"
        reason = "Normal to abnormal finding."
    elif prev_status == "abnormal" and curr_status == "normal":
        direction = "improving"
        reason = "Abnormal to normal finding."
    elif prev_status == "abnormal" and curr_status == "abnormal":
        if previous_diagnosis == current_diagnosis:
            direction = "unchanged"
            reason = "Same abnormal finding."
        else:
            direction = "changed"
            reason = "Different abnormal finding."
    else:  # normal -> normal
        direction = "unchanged"
        if previous_diagnosis == current_diagnosis:
            reason = "Same normal finding."
        else:
            reason = "Different normal finding."

    return {
        "previous_diagnosis": previous_diagnosis,
        "current_diagnosis": current_diagnosis,
        "days_between": days_between,
        "confidence_delta": confidence_delta,
        "direction": direction,
        "interpretation": reason,
    }


@tool(args_schema=CalculateTemporalProgressionSchema)
async def calculate_temporal_progression(
    current_scan_id: str,
    config: RunnableConfig,
    previous_scan_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute progression between diagnostic results of two scans of the same modality.

    Args:
        current_scan_id (str): Identifier of the scan to be assessed.
        previous_scan_id (Optional[str]): Identifier of a specific previous scan (optional).
        config (RunnableConfig): Injected LangGraph config containing the db_pool.

    Returns:
        Dict[str, Any]: Dictionary containing progression results.
    """
    auth_user_id = config.get("configurable", {}).get("auth_user_id")
    if not auth_user_id:
        return {
            "interpretation": "Authentication error: auth_user_id not found in context.",
        }

    db_pool = config.get("configurable", {}).get("db_pool") if config else None
    if db_pool is not None:
        async with db_pool.acquire() as conn:
            return await _temporal_progression_impl(conn, auth_user_id, current_scan_id, previous_scan_id)
    else:
        dsn = _get_config().database_url
        if not dsn:
            return {
                "interpretation": "DATABASE_URL environment variable not set — cannot query scans.",
            }

        conn = await asyncpg.connect(dsn)
        try:
            return await _temporal_progression_impl(conn, auth_user_id, current_scan_id, previous_scan_id)
        finally:
            await conn.close()


@tool(args_schema=QueryPatientMetricsSchema)
async def query_patient_metrics(
    config: RunnableConfig,
) -> str:
    """Retrieve profile information for a patient.

    Args:
        config (RunnableConfig): Injected LangGraph config containing the db_pool.

    Returns:
        str: A newline-separated string of profile information, or a
        descriptive error/not-found message.
    """
    auth_user_id = config.get("configurable", {}).get("auth_user_id")
    if not auth_user_id:
        return "Authentication error: auth_user_id not found in context."
    patient_id = auth_user_id

    async def _query_metrics(conn: asyncpg.Connection) -> str:
        row = await conn.fetchrow(
            "SELECT full_name, gender, date_of_birth, location, medical_history FROM patient_records WHERE user_id = $1", 
            uuid.UUID(patient_id)
        )
        if row:
            metrics = []
            for key, value in row.items():
                if value is not None:
                    metrics.append(f"{key}: {value}")
            if metrics:
                return f"Profile for '{patient_id}':\n" + "\n".join(metrics)
            else:
                return f"Patient '{patient_id}' found, but no profile fields recorded."
        return f"No patient records found for '{patient_id}'."

    db_pool = config.get("configurable", {}).get("db_pool") if config else None
    if db_pool is not None:
        async with db_pool.acquire() as conn:
            return await _query_metrics(conn)
    else:
        dsn = _get_config().database_url
        if not dsn:
            return "DATABASE_URL environment variable not set — cannot query patient profile."
        conn = await asyncpg.connect(dsn)
        try:
            return await _query_metrics(conn)
        finally:
            await conn.close()
