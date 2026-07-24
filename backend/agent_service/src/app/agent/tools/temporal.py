"""L2 temporal progression tool and patient metrics retrieval.

Provides database-backed embedding vector comparison for tracking disease
progression over time, and tabular patient metric retrieval for clinical
context enrichment.
"""


import logging
import math
from typing import Annotated, Any, Dict, List, Optional

import asyncpg
from asyncpg import Pool
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from langchain_core.runnables import RunnableConfig
from app.models.schemas import CalculateTemporalProgressionSchema, QueryPatientMetricsSchema
from app.utils.vector_utils import _vec_to_list

logger = logging.getLogger(__name__)


def _get_config() -> 'AgentConfig':
    """Lazily instantiate the service configuration on first access."""
    from app.core.config import AgentConfig
    return AgentConfig()


from app.models.schemas import ListRecentScansSchema
import json

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
        SELECT scan_id, scan_type, scan_status, scan_date, ai_diagnosis, confidence
        FROM scan_results
        WHERE user_id = $1
        ORDER BY scan_date DESC
        LIMIT $2
    """

    async def _fetch(conn: asyncpg.Connection) -> str:
        try:
            import uuid
            rows = await conn.fetch(query, uuid.UUID(auth_user_id), limit)
            if not rows:
                return "No recent scans found."
            
            scans = []
            for row in rows:
                scans.append({
                    "scan_id": str(row["scan_id"]),
                    "scan_type": row["scan_type"],
                    "scan_status": row["scan_status"],
                    "scan_date": row["scan_date"].isoformat() if row["scan_date"] else None,
                    "ai_diagnosis": row["ai_diagnosis"],
                    "confidence": float(row["confidence"]) if row["confidence"] is not None else None,
                })
            return json.dumps(scans, indent=2)
        except Exception as exc:
            logger.exception("Failed to query recent scans: %s", exc)
            return f"Database error: {exc}"

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



_EMBED_DIM = 256
_SIGNIFICANT_THRESHOLD = 0.5


async def _temporal_progression_impl(
    conn: asyncpg.Connection,
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
        Dict[str, Any]: Dictionary containing ``l2_distance``, ``interpretation``,
        and ``is_significant`` flag.
    """
    # Fetch current scan
    current = await conn.fetchrow(
        """
        SELECT embedding, modality, primary_condition, patient_id
        FROM patient_scans
        WHERE id = $1 AND patient_id = $2
        """,
        current_scan_id, auth_user_id
    )
    if current is None:
        return {
            "l2_distance": None,
            "interpretation": f"Current scan '{current_scan_id}' not found.",
            "is_significant": None,
        }

    current_vector = _vec_to_list(current["embedding"])
    if current_vector is None or len(current_vector) != _EMBED_DIM:
        return {
            "l2_distance": None,
            "interpretation": (
                f"Current scan embedding missing or not {_EMBED_DIM}-dimensional."
            ),
            "is_significant": None,
        }

    modality = current["modality"]
    condition = current["primary_condition"]
    patient_id = current["patient_id"]

    # Retrieve previous vector
    if previous_scan_id is not None:
        prev_row = await conn.fetchrow(
            "SELECT embedding, patient_id FROM patient_scans WHERE id = $1 AND patient_id = $2", previous_scan_id, auth_user_id
        )
        if prev_row is None:
            return {
                "l2_distance": None,
                "interpretation": f"Previous scan '{previous_scan_id}' not found.",
                "is_significant": None,
            }
        prev_vector = _vec_to_list(prev_row["embedding"])
    else:
        # Disease-specific matching
        prev_row = await conn.fetchrow(
            """
            SELECT embedding
            FROM patient_scans
            WHERE patient_id = $1
              AND modality = $2
              AND primary_condition = $3
              AND id != $4
            ORDER BY created_at DESC
            LIMIT 1
            """,
            patient_id,
            modality,
            condition,
            current_scan_id,
        )
        if prev_row is None:
            return {
                "l2_distance": None,
                "interpretation": (
                    "No historical scans for this specific condition "
                    "found for comparison."
                ),
                "is_significant": None,
            }
        prev_vector = _vec_to_list(prev_row["embedding"])

    if prev_vector is None or len(prev_vector) != _EMBED_DIM:
        return {
            "l2_distance": None,
            "interpretation": (
                f"Previous scan embedding missing or not {_EMBED_DIM}-dimensional."
            ),
            "is_significant": None,
        }

    # Compute L2 distance
    distance = math.dist(current_vector, prev_vector)
    significant = distance > _SIGNIFICANT_THRESHOLD
    interpretation = (
        f"L2 distance = {distance:.4f}; "
        f"{'significant' if significant else 'no significant'} progression "
        f"(threshold = {_SIGNIFICANT_THRESHOLD})."
    )

    return {
        "l2_distance": round(distance, 6),
        "interpretation": interpretation,
        "is_significant": significant,
    }


@tool(args_schema=CalculateTemporalProgressionSchema)
async def calculate_temporal_progression(
    current_scan_id: str,
    config: RunnableConfig,
    previous_scan_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute L2 (Euclidean) distance between diagnostic embedding vectors of two scans.

    If the distance exceeds 0.5, significant morphological progression (or
    lesion growth) is indicated.

    When a **previous scan identifier is not provided**, the tool performs
    **disease-specific matching**: it looks up the most recent prior scan of
    the same patient, same modality, and same ``primary_condition``
    (e.g. Cardiomegaly).

    Args:
        current_scan_id (str): Identifier of the scan to be assessed.
        previous_scan_id (Optional[str]): Identifier of a specific previous scan (optional).
        config (RunnableConfig): Injected LangGraph config containing the db_pool.

    Returns:
        Dict[str, Any]: Dictionary containing ``l2_distance``, ``interpretation``,
        and ``is_significant`` flag.  On error, ``l2_distance`` and
        ``is_significant`` are ``None`` with a descriptive
        ``interpretation``.
    """
    auth_user_id = config.get("configurable", {}).get("auth_user_id")
    if not auth_user_id:
        return {
            "l2_distance": None,
            "interpretation": "Authentication error: auth_user_id not found in context.",
            "is_significant": None,
        }

    db_pool = config.get("configurable", {}).get("db_pool") if config else None
    if db_pool is not None:
        try:
            async with db_pool.acquire() as conn:
                return await _temporal_progression_impl(conn, auth_user_id, current_scan_id, previous_scan_id)
        except Exception as exc:
            logger.exception("Temporal progression computation failed: %s", exc)
            return {
                "l2_distance": None,
                "interpretation": f"Error computing temporal progression: {exc}",
                "is_significant": None,
            }
    else:
        dsn = _get_config().database_url
        if not dsn:
            return {
                "l2_distance": None,
                "interpretation": "DATABASE_URL environment variable not set — cannot query scans.",
                "is_significant": None,
            }

        conn: Optional[asyncpg.Connection] = None
        try:
            conn = await asyncpg.connect(dsn)
            return await _temporal_progression_impl(conn, auth_user_id, current_scan_id, previous_scan_id)
        except Exception as exc:
            logger.exception("Temporal progression computation failed: %s", exc)
            return {
                "l2_distance": None,
                "interpretation": f"Error computing temporal progression: {exc}",
                "is_significant": None,
            }
        finally:
            if conn is not None:
                await conn.close()


@tool(args_schema=QueryPatientMetricsSchema)
async def query_patient_metrics(
    config: RunnableConfig,
) -> str:
    """Retrieve tabular metrics (e.g. age, heart rate, blood pressure) for a patient.

    Queries the ``patient_metrics`` table first.  If that table does not exist
    or contains no rows, falls back to the ``patients`` table.

    Args:
        config (RunnableConfig): Injected LangGraph config containing the db_pool.

    Returns:
        str: A newline-separated string of key-value metric pairs, or a
        descriptive error/not-found message.
    """
    auth_user_id = config.get("configurable", {}).get("auth_user_id")
    if not auth_user_id:
        return "Authentication error: auth_user_id not found in context."
    patient_id = auth_user_id

    async def _query_metrics(conn: asyncpg.Connection) -> str:
        import uuid
        # Try patient_metrics first
        try:
            row = await conn.fetchrow(
                "SELECT * FROM patient_metrics WHERE patient_id = $1 ORDER BY created_at DESC LIMIT 1",
                uuid.UUID(patient_id),
            )
            if row:
                metrics: List[str] = []
                for key, value in row.items():
                    if key not in ("id", "patient_id", "created_at", "updated_at") and value is not None:
                        metrics.append(f"{key}: {value}")
                if metrics:
                    return f"Metrics for patient '{patient_id}':\n" + "\n".join(metrics)
        except asyncpg.PostgresError as exc:
            logger.debug("patient_metrics table query failed (may not exist): %s", exc)

        # Fallback to patients table
        try:
            row = await conn.fetchrow(
                "SELECT * FROM patients WHERE id = $1", uuid.UUID(patient_id)
            )
            if row:
                metrics = []
                for key, value in row.items():
                    if key not in ("id", "created_at", "updated_at") and value is not None:
                        metrics.append(f"{key}: {value}")
                if metrics:
                    return f"Patient info for '{patient_id}':\n" + "\n".join(metrics)
                else:
                    return f"Patient '{patient_id}' found, but no metrics recorded."
        except asyncpg.PostgresError as exc:
            logger.debug("patients table query failed (may not exist): %s", exc)

        return f"No metrics found for patient '{patient_id}'."

    db_pool = config.get("configurable", {}).get("db_pool") if config else None
    if db_pool is not None:
        try:
            async with db_pool.acquire() as conn:
                return await _query_metrics(conn)
        except Exception as exc:
            logger.exception("Error querying patient metrics: %s", exc)
            return f"An error occurred while querying patient metrics: {exc}"
    else:
        dsn = _get_config().database_url
        if not dsn:
            return "DATABASE_URL environment variable not set — cannot query patient metrics."

        conn: Optional[asyncpg.Connection] = None
        try:
            conn = await asyncpg.connect(dsn)
            return await _query_metrics(conn)
        except Exception as exc:
            logger.exception("Error querying patient metrics: %s", exc)
            return f"An error occurred while querying patient metrics: {exc}"
        finally:
            if conn is not None:
                await conn.close()
