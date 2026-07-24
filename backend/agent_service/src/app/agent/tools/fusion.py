"""Multimodal fusion tool with clinical severity weighting and selective orchestration.

Provides two tools:

- ``fuse_multimodal_findings`` — Pure computation that aggregates multi-modality
  diagnostic results into a clinically weighted risk score.
- ``orchestrate_fusion`` — Database-backed tool that fetches inference payloads
  for selected scans before fusion.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

import asyncpg
from asyncpg import Pool
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from langchain_core.runnables import RunnableConfig
from app.models.schemas import OrchestrateFusionSchema

logger = logging.getLogger(__name__)


def _get_config() -> 'AgentConfig':
    """Lazily instantiate the service configuration on first access."""
    from app.core.config import AgentConfig
    return AgentConfig()


# Clinical severity multipliers per modality.
# ECG findings carry the highest weight due to acute cardiac risk.
_MODALITY_WEIGHTS: Dict[str, float] = {
    "ECG": 1.5,
    "CXR": 1.2,
    "Skin": 1.0,
}

_CRITICAL_THRESHOLD = 0.85


@tool
async def fuse_multimodal_findings(
    cxr_results: Optional[Dict[str, Any]] = None,
    ecg_results: Optional[Dict[str, Any]] = None,
    skin_results: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Aggregate multi-modality diagnostic results into a clinically weighted risk score.

    The weighted severity for each contributed modality is computed as
    ``max_probability × modality_weight``.  The **aggregated_risk_score** is
    the weighted mean of per-modality severity scores, normalized by the sum of
    applied modality weights to produce a value in [0.0, 1.0].  A critical
    alert is raised if the score meets or exceeds the system threshold (0.85).

    Args:
        cxr_results (Optional[Dict[str, Any]]): Chest X-ray inference payload containing
            ``predicted_class`` and ``probabilities`` (optional).
        ecg_results (Optional[Dict[str, Any]]): ECG inference payload containing ``predicted_class``
            and ``probabilities`` (optional).
        skin_results (Optional[Dict[str, Any]]): Skin-lesion inference payload containing
            ``predicted_class`` and ``probabilities`` (optional).

    Returns:
        Dict[str, Any]: A dictionary with ``aggregated_risk_score``, a list of
        ``detected_conditions``, and a ``critical_alert`` boolean.
    """
    weighted_scores: List[float] = []
    applied_weights: List[float] = []
    conditions: List[str] = []

    def _process(entry: Optional[Dict[str, Any]], modality: str, weight: float) -> None:
        if entry is None:
            return
        predicted = entry.get("predicted_class")
        if predicted:
            conditions.append(f"{modality}: {predicted}")
        prob_map = entry.get("probabilities")
        if isinstance(prob_map, dict) and prob_map:
            max_conf = max(prob_map.values())
            weighted_scores.append(max_conf * weight)
            applied_weights.append(weight)

    _process(cxr_results, "CXR", _MODALITY_WEIGHTS["CXR"])
    _process(ecg_results, "ECG", _MODALITY_WEIGHTS["ECG"])
    _process(skin_results, "Skin", _MODALITY_WEIGHTS["Skin"])

    # Normalize: sum of weighted scores divided by sum of applied weights.
    aggregated_risk_score = (
        sum(weighted_scores) / sum(applied_weights)
        if applied_weights
        else 0.0
    )
    critical_alert = aggregated_risk_score >= _CRITICAL_THRESHOLD

    return {
        "aggregated_risk_score": round(aggregated_risk_score, 4),
        "detected_conditions": conditions,
        "critical_alert": critical_alert,
    }


async def _run_fusion_queries(
    conn: asyncpg.Connection,
    auth_user_id: str,
    selected_scan_ids: Optional[List[uuid.UUID]],
) -> Dict[str, Any]:
    """Execute fusion orchestration queries against an open database connection.

    Extracts the query logic so both pool-backed and standalone connection
    paths share one implementation.

    Args:
        conn: Active asyncpg connection.
        auth_user_id: Unique user identifier for tenant isolation.
        selected_scan_ids: Optional list of scan identifiers chosen for fusion.

    Returns:
        Dict[str, Any]: Modality-keyed inference payloads or a descriptive message.
    """
    try:
        # IDs provided
        if selected_scan_ids and len(selected_scan_ids) > 0:
            rows = await conn.fetch(
                """
                SELECT id, modality, predicted_class, probabilities
                FROM scan_results
                WHERE id = ANY($1::uuid[]) AND user_id = $2
                """,
                selected_scan_ids, auth_user_id
            )
            # Group by modality, keep the last seen payload
            per_modality: Dict[str, Dict[str, Any]] = {}
            for row in rows:
                mod = row["modality"]
                prob = row["probabilities"]
                try:
                    prob_dict = dict(prob) if prob else {}
                except Exception as exc:
                    raise ValueError(f"Failed to parse probabilities for modality {mod}") from exc
                per_modality[mod] = {
                    "predicted_class": row.get("predicted_class"),
                    "probabilities": prob_dict,
                }

            result: Dict[str, Any] = {}
            if "CXR" in per_modality:
                result["cxr_results"] = per_modality["CXR"]
            if "ECG" in per_modality:
                result["ecg_results"] = per_modality["ECG"]
            if "Skin" in per_modality:
                result["skin_results"] = per_modality["Skin"]

            if not result:
                return {"message": "No valid scans found for the provided IDs."}
            return result

        # IDs missing: query recent scans
        rows = await conn.fetch(
            """
            SELECT id, modality, predicted_class, created_at
            FROM scan_results
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT 10
            """,
            auth_user_id,
        )

        if not rows:
            return {"message": "No recent scans found for this patient."}

        scan_lines: List[str] = []
        for r in rows:
            scan_lines.append(
                f"{r['id']} ({r['modality']}, predicted={r.get('predicted_class', 'N/A')})"
            )
        msg = (
            "Found multiple recent scans for this patient: "
            + "; ".join(scan_lines)
            + ". Please ask the user which specific scans they want to fuse by passing their IDs."
        )
        return {"message": msg}

    except Exception as exc:
        logger.exception("Fusion orchestration failed: %s", exc)
        raise RuntimeError("Error during fusion orchestration.") from exc


import uuid
@tool(args_schema=OrchestrateFusionSchema)
async def orchestrate_fusion(
    selected_scan_ids: Optional[List[uuid.UUID]] = None,
    config: RunnableConfig = None,
) -> Dict[str, Any]:
    """Selective fusion orchestrator that fetches inference payloads for chosen scans.

    When ``selected_scan_ids`` are provided the tool queries those scans and
    returns their inference payloads keyed by modality (``cxr_results``,
    ``ecg_results``, ``skin_results``) so the LLM can pass them to
    ``fuse_multimodal_findings``.

    When ``selected_scan_ids`` are absent, the tool queries the patient's
    recent scans and instructs the LLM to ask the user which specific
    scans they want to fuse.

    Args:
        selected_scan_ids (Optional[List[uuid.UUID]]): Optional list of scan identifiers chosen by the
            user for fusion.
        config (RunnableConfig): Injected LangGraph config containing the db_pool and auth_user_id.

    Returns:
        Dict[str, Any]: Dictionary containing the required payloads for subsequent fusion,
        or a human-readable message requesting further input.
    """
    auth_user_id = config.get("configurable", {}).get("auth_user_id") if config else None
    if not auth_user_id:
        return {"message": "Authentication error: auth_user_id not found in context."}

    db_pool = config.get("configurable", {}).get("db_pool") if config else None
    if db_pool is not None:
        async with db_pool.acquire() as conn:
            return await _run_fusion_queries(conn, auth_user_id, selected_scan_ids)
    else:
        dsn = _get_config().database_url
        if not dsn:
            return {"message": "DATABASE_URL environment variable not set — cannot fetch scans."}
        conn = await asyncpg.connect(dsn)
        try:
            return await _run_fusion_queries(conn, auth_user_id, selected_scan_ids)
        finally:
            await conn.close()
