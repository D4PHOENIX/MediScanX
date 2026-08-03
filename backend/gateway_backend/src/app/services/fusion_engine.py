"""Gateway-local fusion scoring engine.

NOTE: This is a gateway-local copy of the fusion scoring logic.
The definitive source of truth is
``agent_service/src/app/agent/tools/fusion.py``.
These two files MUST be updated together to ensure cross-service consistency.

DRIFT RISK: Unlike labels.py (two small dicts), this file duplicates a full
computational engine — the clinically weighted risk-score aggregation.  Any
future change to ``fuse_multimodal_findings`` in the agent service must be
ported here explicitly.  The duplication was chosen over inventing a new
cross-service HTTP RPC pattern under time pressure (the only existing
``agent_service`` call is an opaque SSE stream proxy to ``/chat``, which
cannot be reused for structured function calls).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.utils.labels import _ABNORMAL_LABELS, _NORMAL_LABELS

logger = logging.getLogger(__name__)

# Clinical severity multipliers per modality.
# ECG findings carry the highest weight due to acute cardiac risk.
# Must match agent_service/src/app/agent/tools/fusion.py exactly.
_MODALITY_WEIGHTS: Dict[str, float] = {
    "ecg": 1.5,
    "cxr": 1.2,
    "skin": 1.0,
}

_CRITICAL_THRESHOLD: float = 0.85


def compute_risk_level(score: float) -> str:
    """Map an aggregated risk score to a named risk tier.

    Inclusive lower bound per tier — boundary values belong to the higher tier.

    Args:
        score: The aggregated risk score in [0.0, 1.0].

    Returns:
        str: One of ``"CRITICAL"``, ``"HIGH"``, ``"MODERATE"``, or ``"LOW"``.
    """
    if score >= 0.85:
        return "CRITICAL"
    if score >= 0.60:
        return "HIGH"
    if score >= 0.30:
        return "MODERATE"
    return "LOW"


def run_fusion_scoring(
    cxr_results: Optional[Dict[str, Any]] = None,
    ecg_results: Optional[Dict[str, Any]] = None,
    skin_results: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Aggregate multi-modality diagnostic results into a clinically weighted risk score.

    This is a synchronous, pure-computation port of ``fuse_multimodal_findings``
    from agent_service.  The scoring logic — including all exclusion rules for
    out-of-range confidence, empty ai_diagnosis, and unrecognised labels — is
    preserved exactly.  Do not simplify or clean up anything while porting.

    The severity for an abnormal finding is computed as ``confidence × modality_weight``.
    A normal finding contributes zero severity but still applies its weight, pulling
    the aggregate score down.  The ``overall_risk_score`` is a weighted mean of
    confidences (where normal findings act as 0.0 confidence), normalized by the
    sum of applied modality weights to produce a value in [0.0, 1.0].

    A critical alert is raised **only** when ``fusion_performed`` is True and
    the score meets or exceeds the critical threshold (0.85).  This rule must not
    be weakened — a lone single-modality confidence must never be presented as a
    fused risk tier.

    Args:
        cxr_results: CXR inference payload with ``ai_diagnosis`` and ``confidence``.
        ecg_results: ECG inference payload with ``ai_diagnosis`` and ``confidence``.
        skin_results: Skin-lesion inference payload with ``ai_diagnosis`` and ``confidence``.

    Returns:
        Dict[str, Any]: Keys: ``overall_risk_score``, ``risk_level`` (str or None),
        ``critical_alert``, ``fusion_performed``, ``unscored`` (list), and
        ``scored_modalities`` (list of dicts with modality/ai_diagnosis/confidence/status).
    """
    weighted_scores: List[float] = []
    applied_weights: List[float] = []
    scored_modalities: List[Dict[str, Any]] = []
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

        status = "normal" if is_normal else "abnormal"
        scored_modalities.append(
            {
                "modality": modality,
                "ai_diagnosis": predicted,
                "confidence": conf,
                "status": status,
            }
        )

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

    risk_level: Optional[str] = compute_risk_level(aggregated_risk_score) if fusion_performed else None

    return {
        "overall_risk_score": round(aggregated_risk_score, 4),
        "risk_level": risk_level,
        "critical_alert": critical_alert,
        "fusion_performed": fusion_performed,
        "unscored": unscored,
        "scored_modalities": scored_modalities,
    }
