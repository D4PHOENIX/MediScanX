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
import uuid

import asyncpg
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
    "ecg": 1.5,
    "cxr": 1.2,
    "skin": 1.0,
}

_CRITICAL_THRESHOLD = 0.85

_NORMAL_LABELS: Dict[str, set[str]] = {
    "cxr": {"No Finding"},
    "ecg": {"NORM"},
    "skin": {
        "Melanocytic nevi",
        "Benign keratosis-like lesions",
        "Dermatofibroma",
        "Vascular lesions",
    },
}

_ABNORMAL_LABELS: Dict[str, set[str]] = {
    "cxr": {
        # CheXpert-14 pathologies
        "Enlarged Cardiomediastinum", "Cardiomegaly", "Lung Opacity",
        "Lung Lesion", "Edema", "Consolidation", "Pneumonia",
        "Atelectasis", "Pneumothorax", "Pleural Effusion",
        "Pleural Other", "Fracture",
        # hierarchical heads
        "Abnormal", "Fluid Accumulation", "Missing Lung Tissue",
        "Cardiac", "Opacity",
    },
    "ecg": {"MI", "STTC", "CD", "HYP"},
    "skin": {"Melanoma", "Basal cell carcinoma", "Actinic keratoses"},
}


@tool
async def fuse_multimodal_findings(
    cxr_results: Optional[Dict[str, Any]] = None,
    ecg_results: Optional[Dict[str, Any]] = None,
    skin_results: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Aggregate multi-modality diagnostic results into a clinically weighted risk score.

    The severity for an abnormal finding is computed as ``confidence × modality_weight``.
    A normal finding contributes zero severity but still applies its weight, pulling
    the aggregate score down. The **aggregated_risk_score** is a weighted mean
    of confidences (where normal findings act as a 0.0 confidence), normalized by
    the sum of applied modality weights to produce a value in [0.0, 1.0]. A critical
    alert is raised if the score meets or exceeds the system threshold (0.85).

    Args:
        cxr_results (Optional[Dict[str, Any]]): Chest X-ray inference payload containing
            ``ai_diagnosis`` and ``confidence`` (optional).
        ecg_results (Optional[Dict[str, Any]]): ECG inference payload containing ``ai_diagnosis``
            and ``confidence`` (optional).
        skin_results (Optional[Dict[str, Any]]): Skin-lesion inference payload containing
            ``ai_diagnosis`` and ``confidence`` (optional).

    Returns:
        Dict[str, Any]: A dictionary with ``aggregated_risk_score``, a list of
        ``detected_conditions``, a ``critical_alert`` boolean, and a ``fusion_performed`` boolean.
    """
    weighted_scores: List[float] = []
    applied_weights: List[float] = []
    conditions: List[str] = []
    unscored: List[str] = []

    def _process(entry: Optional[Dict[str, Any]], modality: str, weight: float) -> None:
        if entry is None:
            return
            
        predicted = entry.get("ai_diagnosis")
        if not predicted:
            unscored.append(f"{modality}: Empty ai_diagnosis")
            return
            
        conf = entry.get("confidence")
        if conf is None or not isinstance(conf, (int, float)) or not (0.0 <= conf <= 1.0):
            unscored.append(f"{modality}: Confidence {conf} outside [0.0, 1.0]")
            return
            
        is_normal = predicted in _NORMAL_LABELS.get(modality, set())
        is_abnormal = predicted in _ABNORMAL_LABELS.get(modality, set())
        
        if not (is_normal or is_abnormal):
            unscored.append(f"{modality}: Unrecognised label '{predicted}'")
            return
            
        conditions.append(f"{modality.upper()}: {predicted}")
        
        if is_normal:
            weighted_scores.append(0.0)
            applied_weights.append(weight)
        else:
            weighted_scores.append(conf * weight)
            applied_weights.append(weight)

    _process(cxr_results, "cxr", _MODALITY_WEIGHTS["cxr"])
    _process(ecg_results, "ecg", _MODALITY_WEIGHTS["ecg"])
    _process(skin_results, "skin", _MODALITY_WEIGHTS["skin"])

    fusion_performed = len(applied_weights) > 1

    if fusion_performed:
        aggregated_risk_score = sum(weighted_scores) / sum(applied_weights)
        critical_alert = aggregated_risk_score >= _CRITICAL_THRESHOLD
    else:
        aggregated_risk_score = (
            sum(weighted_scores) / sum(applied_weights)
            if applied_weights
            else 0.0
        )
        critical_alert = False

    result = {
        "aggregated_risk_score": round(aggregated_risk_score, 4),
        "detected_conditions": conditions,
        "critical_alert": critical_alert,
        "fusion_performed": fusion_performed,
    }
    if unscored:
        result["unscored"] = unscored

    return result


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
                SELECT scan_id, modality, ai_diagnosis, confidence
                FROM scan_results
                WHERE scan_id = ANY($1::uuid[]) AND user_id = $2
                """,
                selected_scan_ids, uuid.UUID(auth_user_id)
            )
            # Group by modality, keep the last seen payload
            per_modality: Dict[str, Dict[str, Any]] = {}
            unscored: List[str] = []
            
            for row in rows:
                mod = row["modality"]
                if mod is None:
                    unscored.append(f"scan {row['scan_id']}: Modality IS NULL")
                    continue
                
                mod_lower = mod.lower()
                if mod_lower not in _MODALITY_WEIGHTS:
                    unscored.append(f"{mod_lower}: Unrecognised modality")
                    continue
                
                if mod_lower in per_modality:
                    return {
                        "message": (
                            f"Multiple {mod_lower} scans were selected. Fusion combines "
                            f"one scan per modality — please select a single {mod_lower} scan."
                        )
                    }
                
                per_modality[mod_lower] = {
                    "ai_diagnosis": row.get("ai_diagnosis"),
                    "confidence": row.get("confidence"),
                }

            result: Dict[str, Any] = {}
            if "cxr" in per_modality:
                result["cxr_results"] = per_modality["cxr"]
            if "ecg" in per_modality:
                result["ecg_results"] = per_modality["ecg"]
            if "skin" in per_modality:
                result["skin_results"] = per_modality["skin"]

            if not result:
                return {"message": "No valid scans found for the provided IDs.", "unscored": unscored} if unscored else {"message": "No valid scans found for the provided IDs."}
            
            if unscored:
                result["unscored"] = unscored
                
            return result

        # IDs missing: query recent scans
        rows = await conn.fetch(
            """
            SELECT scan_id, modality, ai_diagnosis, created_at
            FROM scan_results
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT 10
            """,
            uuid.UUID(auth_user_id),
        )

        if not rows:
            return {"message": "No recent scans found for this patient."}

        scan_lines: List[str] = []
        for r in rows:
            scan_lines.append(
                f"{r['scan_id']} ({r['modality']}, predicted={r.get('ai_diagnosis', 'N/A')})"
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


@tool(args_schema=OrchestrateFusionSchema)
async def orchestrate_fusion(
    config: RunnableConfig,
    selected_scan_ids: Optional[List[uuid.UUID]] = None,
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
