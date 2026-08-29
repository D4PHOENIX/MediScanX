"""Deterministic multimodal fusion endpoint for the MediScanX frontend.

POST /api/v1/fusion/fuse — returns a structured gauge payload suitable for
driving a dedicated fusion screen with risk gauges and per-modality breakdown
cards.  This endpoint reuses the B22 scoring logic (ported to
``app.utils.fusion_engine``) and does **not** call the LangGraph agent.

Auth pattern, error handling, and query construction mirror ``scans_router.py``
exactly — JWT-derived identity via ``get_current_user``, every query scoped to
``user_id``, ``asyncpg.PostgresError`` → 503.
"""

from __future__ import annotations

import logging
import uuid
from app.utils.validation_utils import parse_uuid
from typing import Any, Dict, List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.security import get_current_user
from app.models.schemas import FusionRequest, FusionResponse, ModalityRisk
from app.services.fusion_engine import run_fusion_scoring
from app.services.llm_service import generate_hedged_text

logger: logging.Logger = logging.getLogger(__name__)

router: APIRouter = APIRouter(prefix="/fusion", tags=["fusion"])

# Ordered list of supported modalities — used for auto-selection and result
# ordering.  Must stay in sync with _MODALITY_WEIGHTS in fusion_engine.py.
_MODALITIES: List[str] = ["cxr", "ecg", "skin"]


def _build_findings_summary(modality_risks: List[ModalityRisk]) -> str:
    """Build the findings_summary string from scored modality entries.

    Format: ``"{MODALITY}: {diagnosis} ({status}, {confidence*100:.1f}%)."``
    joined by single spaces, one clause per scored modality.  No LLM call.
    No inference.  Pure string formatting.

    Args:
        modality_risks: Scored modality entries in result order.

    Returns:
        str: The formatted findings summary, or empty string if no entries.
    """
    clauses = [
        f"{mr.modality.upper()}: {mr.ai_diagnosis} ({mr.status}, {mr.confidence * 100:.1f}%)."
        for mr in modality_risks
    ]
    return " ".join(clauses)


async def _run_autoselect_queries(
    conn: asyncpg.Connection,
    user_uuid: uuid.UUID,
) -> Dict[str, Dict[str, Any]]:
    """Fetch the most recent scan per modality for the authenticated caller.

    One query per modality (ORDER BY scan_date DESC LIMIT 1 per modality,
    modality IS NOT NULL).  Scoped to ``user_uuid`` — no client-supplied
    user_id accepted.

    Args:
        conn: Active asyncpg connection.
        user_uuid: Authenticated caller UUID for tenant isolation.

    Returns:
        Dict[str, Dict[str, Any]]: Modality-keyed payloads for any modalities
        that have at least one scan.  Keys are modality strings (``cxr``,
        ``ecg``, ``skin``); values have ``ai_diagnosis`` and ``confidence``.
    """
    per_modality: Dict[str, Dict[str, Any]] = {}
    for mod in _MODALITIES:
        row = await conn.fetchrow(
            """
            SELECT ai_diagnosis, confidence
            FROM scan_results
            WHERE user_id = $1 AND modality = $2 AND modality IS NOT NULL
            ORDER BY scan_date DESC NULLS LAST
            LIMIT 1
            """,
            user_uuid,
            mod,
        )
        if row:
            per_modality[mod] = {
                "ai_diagnosis": row["ai_diagnosis"],
                "confidence": row["confidence"],
            }
    return per_modality


async def _run_selected_queries(
    conn: asyncpg.Connection,
    user_uuid: uuid.UUID,
    scan_uuids: List[uuid.UUID],
) -> Dict[str, Any]:
    """Fetch inference payloads for the caller-supplied scan IDs.

    Replicates _run_fusion_queries logic from agent_service verbatim:
    - Scoped to user_uuid (tenant isolation).
    - Returns a message dict when duplicate modalities are detected.
    - Accumulates modality IS NULL / unrecognised modality into unscored.

    Args:
        conn: Active asyncpg connection.
        user_uuid: Authenticated caller UUID for tenant isolation.
        scan_uuids: Validated UUID objects for the requested scans.

    Returns:
        Dict[str, Any]: Either ``{"message": str}`` on duplicate-modality
        rejection, or ``{"per_modality": dict, "unscored": list}`` on success.
    """
    from app.services.fusion_engine import _MODALITY_WEIGHTS  # noqa: PLC0415

    rows = await conn.fetch(
        """
        SELECT scan_id, modality, ai_diagnosis, confidence
        FROM scan_results
        WHERE scan_id = ANY($1::uuid[]) AND user_id = $2
        """,
        scan_uuids,
        user_uuid,
    )

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
            # Matching _run_fusion_queries: reject loudly, do not silently keep one.
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

    return {"per_modality": per_modality, "unscored": unscored}


@router.post(
    "/fuse",
    response_model=FusionResponse,
    status_code=status.HTTP_200_OK,
    summary="Deterministic multimodal fusion for the authenticated caller.",
)
async def fuse(
    request: Request,
    body: FusionRequest,
    user_id: str = Depends(get_current_user),
) -> FusionResponse:
    """Aggregate multimodal diagnostic results into a clinically weighted risk score.

    When ``selected_scan_ids`` is provided, those scans are fused.  Duplicate
    modalities among the selected scans are rejected with a descriptive message
    (matching ``_run_fusion_queries``'s existing duplicate-modality behavior —
    not silently resolved).

    When ``selected_scan_ids`` is omitted, the most recent scan per modality is
    auto-selected for the caller (ORDER BY scan_date DESC LIMIT 1 per modality).
    This differs from the agent tool's no-IDs path, which returns a conversational
    clarification message — that behavior is not appropriate for a screen that
    needs structured data back.

    ``risk_level`` and ``critical_alert`` inherit B22's rule: they are computed
    **only** when ``fusion_performed`` is true (two or more modalities scored).
    A single-modality result must never be presented as a fused risk tier.

    Args:
        request: FastAPI request context (provides ``db_pool``).
        body: Validated request payload.
        user_id: JWT-derived authenticated caller identifier.

    Returns:
        FusionResponse: Structured gauge payload.

    Raises:
        HTTPException 422: When any ``selected_scan_ids`` entry is not a valid UUID.
        HTTPException 503: When the database pool is unavailable or a query fails.
    """
    db_pool: asyncpg.Pool | None = request.app.state.db_pool
    if not db_pool:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection pool unavailable.",
        )

    user_uuid = parse_uuid(user_id, 'subject claim')

    # --- Validate selected_scan_ids when provided ---
    scan_uuids: Optional[List[uuid.UUID]] = None
    if body.selected_scan_ids is not None:
        validated: List[uuid.UUID] = []
        for raw in body.selected_scan_ids:
            validated.append(parse_uuid(raw, 'selected_scan_ids'))
        scan_uuids = validated

    try:
        async with db_pool.acquire() as conn:
            if scan_uuids is not None:
                # --- Caller-supplied IDs path ---
                result = await _run_selected_queries(conn, user_uuid, scan_uuids)

                # Duplicate-modality rejection: return message-style response
                if "message" in result and "per_modality" not in result:
                    return FusionResponse(
                        overall_risk_score=0.0,
                        risk_level=None,
                        critical_alert=False,
                        fusion_performed=False,
                        unscored=[],
                        modality_risks=[],
                        findings_summary="",
                        message=result["message"],
                    )

                per_modality = result.get("per_modality", {})
                query_unscored: List[str] = result.get("unscored", [])

                if not per_modality:
                    return FusionResponse(
                        overall_risk_score=0.0,
                        risk_level=None,
                        critical_alert=False,
                        fusion_performed=False,
                        unscored=query_unscored,
                        modality_risks=[],
                        findings_summary="",
                        message="No valid scans found for the provided IDs.",
                    )

            else:
                # --- Auto-select path ---
                per_modality = await _run_autoselect_queries(conn, user_uuid)
                query_unscored = []

                if not per_modality:
                    return FusionResponse(
                        overall_risk_score=0.0,
                        risk_level=None,
                        critical_alert=False,
                        fusion_performed=False,
                        unscored=[],
                        modality_risks=[],
                        findings_summary="",
                        message="No recent scans found for this patient.",
                    )

    except asyncpg.PostgresError as exc:
        logger.error("Database failure in /fusion/fuse: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database query failed",
        ) from exc

    # --- Scoring ---
    scoring_result = run_fusion_scoring(
        cxr_results=per_modality.get("cxr"),
        ecg_results=per_modality.get("ecg"),
        skin_results=per_modality.get("skin"),
    )

    # Merge unscored from the DB query and from the scoring engine
    all_unscored: List[str] = query_unscored + scoring_result["unscored"]

    # Build modality_risks — only scored modalities; unscored appear in unscored only
    modality_risks = [
        ModalityRisk(
            modality=entry["modality"],
            ai_diagnosis=entry["ai_diagnosis"],
            confidence=entry["confidence"],
            status=entry["status"],
        )
        for entry in scoring_result["scored_modalities"]
    ]

    findings_summary = _build_findings_summary(modality_risks)

    clinical_correlation = None
    abnormal_risks = [mr for mr in modality_risks if mr.status == "abnormal"]
    if len(abnormal_risks) >= 2:
        findings_list = "\n".join(
            f"{mr.modality.upper()}: {mr.ai_diagnosis} ({mr.status}, {mr.confidence * 100:.1f}%)"
            for mr in abnormal_risks
        )
        prompt = (
            "Given these findings from independent diagnostic scans of the same\n"
            f"patient: {findings_list}. Write exactly 2 sentences. Never assert that one\n"
            "finding caused another. If these findings have a recognized clinical\n"
            "association, describe that they can occur together and that a clinician\n"
            "reviewing both may find it relevant. If there's no recognized\n"
            "relationship, say so rather than inventing one. Avoid \"is caused by,\" \"is\n"
            "a direct result of,\" \"because of.\" Use \"can be associated with,\" \"may\n"
            "sometimes occur alongside,\" \"worth reviewing together with a doctor.\""
        )
        clinical_correlation = await generate_hedged_text(prompt)

    return FusionResponse(
        overall_risk_score=scoring_result["overall_risk_score"],
        risk_level=scoring_result["risk_level"],
        critical_alert=scoring_result["critical_alert"],
        fusion_performed=scoring_result["fusion_performed"],
        unscored=all_unscored,
        modality_risks=modality_risks,
        findings_summary=findings_summary,
        clinical_correlation=clinical_correlation,
    )
