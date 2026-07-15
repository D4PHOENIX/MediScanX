"""L2 temporal progression tool and patient metrics retrieval.

Provides database-backed embedding vector comparison for tracking disease
progression over time, and tabular patient metric retrieval for clinical
context enrichment.
"""

from __future__ import annotations

import logging
import math
from typing import Annotated, Any, Dict, List, Optional

import asyncpg
from asyncpg import Pool
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)


def _get_config() -> 'AgentConfig':
    """Lazily instantiate the service configuration on first access."""
    from app.core.config import AgentConfig
    return AgentConfig()


_EMBED_DIM = 256
_SIGNIFICANT_THRESHOLD = 0.5


def _vec_to_list(vec: Any) -> Optional[List[float]]:
    """Convert a PostgreSQL vector/array to a plain Python list of floats.

    Handles native Python lists, pgvector string representations, and
    ``None`` values gracefully.

    Args:
        vec (Any): Raw vector value from asyncpg (list, str, or None).

    Returns:
        Optional[List[float]]: A list of floats, or ``None`` if conversion is not possible.
    """
    if vec is None:
        return None
    if isinstance(vec, list):
        return [float(v) for v in vec]
    # In case it's a string representation (pgvector 0.x)
    try:
        return [float(x) for x in vec.strip("[]").split(",")]
    except Exception:
        return None


async def _temporal_progression_impl(
    conn: asyncpg.Connection,
    current_scan_id: str,
    previous_scan_id: Optional[str],
) -> Dict[str, Any]:
    """Core implementation for temporal progression computation.

    Extracted to share logic between pool-backed and standalone connection paths.

    Args:
        conn: Active asyncpg connection.
        current_scan_id: Identifier of the scan to be assessed.
        previous_scan_id: Identifier of a specific previous scan (optional).

    Returns:
        Dict[str, Any]: Dictionary containing ``l2_distance``, ``interpretation``,
        and ``is_significant`` flag.
    """
    # --- Fetch current scan -------------------------------------------------
    current = await conn.fetchrow(
        """
        SELECT embedding, modality, primary_condition, patient_id
        FROM patient_scans
        WHERE id = $1
        """,
        current_scan_id,
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

    # --- Retrieve previous vector -------------------------------------------
    if previous_scan_id is not None:
        prev_row = await conn.fetchrow(
            "SELECT embedding FROM patient_scans WHERE id = $1", previous_scan_id
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

    # --- Compute L2 distance ------------------------------------------------
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


class CalculateTemporalProgressionSchema(BaseModel):
    current_scan_id: str = Field(description="Identifier of the scan to be assessed.")
    previous_scan_id: Optional[str] = Field(default=None, description="Identifier of a specific previous scan (optional).")

@tool(args_schema=CalculateTemporalProgressionSchema)
async def calculate_temporal_progression(
    current_scan_id: str,
    previous_scan_id: Optional[str] = None,
    config: RunnableConfig = None,
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
    db_pool = config.get("configurable", {}).get("db_pool") if config else None
    if db_pool is not None:
        try:
            async with db_pool.acquire() as conn:
                return await _temporal_progression_impl(conn, current_scan_id, previous_scan_id)
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
            return await _temporal_progression_impl(conn, current_scan_id, previous_scan_id)
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


class QueryPatientMetricsSchema(BaseModel):
    patient_id: str = Field(description="The unique identifier of the patient to query.")

@tool(args_schema=QueryPatientMetricsSchema)
async def query_patient_metrics(
    patient_id: str,
    config: RunnableConfig = None,
) -> str:
    """Retrieve tabular metrics (e.g. age, heart rate, blood pressure) for a patient.

    Queries the ``patient_metrics`` table first.  If that table does not exist
    or contains no rows, falls back to the ``patients`` table.

    Args:
        patient_id (str): The unique identifier of the patient to query.
        config (RunnableConfig): Injected LangGraph config containing the db_pool.

    Returns:
        str: A newline-separated string of key-value metric pairs, or a
        descriptive error/not-found message.
    """

    async def _query_metrics(conn: asyncpg.Connection) -> str:
        # Try patient_metrics first
        try:
            row = await conn.fetchrow(
                "SELECT * FROM patient_metrics WHERE patient_id = $1 ORDER BY created_at DESC LIMIT 1",
                patient_id,
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
                "SELECT * FROM patients WHERE id = $1", patient_id
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
