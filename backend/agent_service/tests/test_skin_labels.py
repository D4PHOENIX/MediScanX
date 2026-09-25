"""Tests for agent_service skin label sets and temporal tool behaviour.

Covers:
- The skin normal + abnormal sets in agent labels.py match the skin model's exact class list.
- get_status("Normal skin", "skin") == "normal"
- get_status("Basal cell carcinoma", "skin") == "abnormal"
- Temporal progression: Normal skin -> Basal cell carcinoma yields "worsening".
- Temporal progression: Basal cell carcinoma -> Normal skin yields "improving".

#z8v0kmrkv4  ClickUp B54
"""
import uuid
import pytest
from datetime import datetime

from app.agent.tools.labels import _NORMAL_LABELS, _ABNORMAL_LABELS

# ---------------------------------------------------------------------------
# Ground-truth class list for the skin model (all 8 classes, exact spelling).
# ---------------------------------------------------------------------------
_SKIN_MODEL_CLASSES = {
    "Normal skin",
    "Actinic keratoses",
    "Basal cell carcinoma",
    "Benign keratosis-like lesions",
    "Dermatofibroma",
    "Melanocytic nevi",
    "Melanoma",
    "Vascular lesions",
}


# ---------------------------------------------------------------------------
# Label set integrity (catches drift between gateway and agent copies)
# ---------------------------------------------------------------------------

class TestAgentSkinLabelSets:
    """The agent copy of skin label sets must equal the model's exact class list."""

    def test_normal_skin_label_set_exact(self):
        assert _NORMAL_LABELS["skin"] == {"Normal skin"}, (
            "Agent normal skin label set drifted from model output."
        )

    def test_abnormal_skin_label_set_exact(self):
        assert _ABNORMAL_LABELS["skin"] == {
            "Actinic keratoses",
            "Basal cell carcinoma",
            "Benign keratosis-like lesions",
            "Dermatofibroma",
            "Melanocytic nevi",
            "Melanoma",
            "Vascular lesions",
        }, "Agent abnormal skin label set drifted from model output."

    def test_skin_label_union_equals_model_classes(self):
        union = _NORMAL_LABELS["skin"] | _ABNORMAL_LABELS["skin"]
        assert union == _SKIN_MODEL_CLASSES, (
            f"Agent label union {union!r} does not match model classes {_SKIN_MODEL_CLASSES!r}"
        )

    def test_normal_and_abnormal_are_disjoint(self):
        overlap = _NORMAL_LABELS["skin"] & _ABNORMAL_LABELS["skin"]
        assert overlap == set(), f"Labels appear in both sets: {overlap!r}"

    def test_basal_cell_carcinoma_in_abnormal(self):
        assert "Basal cell carcinoma" in _ABNORMAL_LABELS["skin"]

    def test_dermatofibroma_in_abnormal(self):
        assert "Dermatofibroma" in _ABNORMAL_LABELS["skin"]


# ---------------------------------------------------------------------------
# get_status logic (via temporal tool's internal function)
# ---------------------------------------------------------------------------

def _get_status_from_temporal(label, mod):
    """Re-implement the identical get_status logic that temporal.py uses."""
    if not label:
        return "unknown"
    if label in _NORMAL_LABELS.get(mod, set()):
        return "normal"
    if label in _ABNORMAL_LABELS.get(mod, set()):
        return "abnormal"
    return "unknown"


def test_get_status_normal_skin_is_normal():
    assert _get_status_from_temporal("Normal skin", "skin") == "normal"


def test_get_status_basal_cell_carcinoma_is_abnormal():
    assert _get_status_from_temporal("Basal cell carcinoma", "skin") == "abnormal"


def test_get_status_dermatofibroma_is_abnormal():
    assert _get_status_from_temporal("Dermatofibroma", "skin") == "abnormal"


def test_get_status_melanocytic_nevi_is_abnormal():
    assert _get_status_from_temporal("Melanocytic nevi", "skin") == "abnormal"


def test_get_status_unknown_skin_label_is_unknown():
    assert _get_status_from_temporal("Something Fictional", "skin") == "unknown"


# ---------------------------------------------------------------------------
# Temporal progression with skin labels
# ---------------------------------------------------------------------------

def _setup_mock_config(auth_user_id, fetchrow_side_effect=None):
    from unittest.mock import AsyncMock, MagicMock
    from langchain_core.runnables import RunnableConfig

    mock_conn = AsyncMock()
    mock_conn.fetchrow.side_effect = fetchrow_side_effect
    mock_conn.fetch.return_value = []

    mock_acquire_ctx = MagicMock()
    mock_acquire_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_acquire_ctx
    return RunnableConfig(configurable={"auth_user_id": auth_user_id, "db_pool": mock_pool})


@pytest.mark.asyncio
async def test_skin_normal_to_basal_cell_carcinoma_is_worsening():
    """Normal skin → Basal cell carcinoma must be classified as worsening."""
    from app.agent.tools.temporal import calculate_temporal_progression

    user_id = str(uuid.uuid4())
    curr_id = str(uuid.uuid4())
    prev_id = str(uuid.uuid4())

    def side_effect(query, *args):
        if curr_id in str(args):
            return {
                "scan_id": curr_id, "modality": "skin",
                "ai_diagnosis": "Basal cell carcinoma",
                "confidence": 0.91, "scan_date": datetime(2024, 2, 1),
            }
        return {
            "scan_id": prev_id, "modality": "skin",
            "ai_diagnosis": "Normal skin",
            "confidence": 0.97, "scan_date": datetime(2024, 1, 1),
        }

    config = _setup_mock_config(user_id, fetchrow_side_effect=side_effect)
    res = await calculate_temporal_progression.ainvoke(
        {"current_scan_id": curr_id, "previous_scan_id": prev_id}, config=config
    )
    assert res["direction"] == "worsening", (
        f"Normal skin → BCC should be worsening, got: {res['direction']}"
    )


@pytest.mark.asyncio
async def test_skin_basal_cell_carcinoma_to_normal_skin_is_improving():
    """Basal cell carcinoma → Normal skin must be classified as improving."""
    from app.agent.tools.temporal import calculate_temporal_progression

    user_id = str(uuid.uuid4())
    curr_id = str(uuid.uuid4())
    prev_id = str(uuid.uuid4())

    def side_effect(query, *args):
        if curr_id in str(args):
            return {
                "scan_id": curr_id, "modality": "skin",
                "ai_diagnosis": "Normal skin",
                "confidence": 0.98, "scan_date": datetime(2024, 2, 1),
            }
        return {
            "scan_id": prev_id, "modality": "skin",
            "ai_diagnosis": "Basal cell carcinoma",
            "confidence": 0.91, "scan_date": datetime(2024, 1, 1),
        }

    config = _setup_mock_config(user_id, fetchrow_side_effect=side_effect)
    res = await calculate_temporal_progression.ainvoke(
        {"current_scan_id": curr_id, "previous_scan_id": prev_id}, config=config
    )
    assert res["direction"] == "improving", (
        f"BCC → Normal skin should be improving, got: {res['direction']}"
    )


@pytest.mark.asyncio
async def test_skin_normal_skin_to_melanoma_is_worsening():
    """Normal skin → Melanoma must be classified as worsening."""
    from app.agent.tools.temporal import calculate_temporal_progression

    user_id = str(uuid.uuid4())
    curr_id = str(uuid.uuid4())
    prev_id = str(uuid.uuid4())

    def side_effect(query, *args):
        if curr_id in str(args):
            return {
                "scan_id": curr_id, "modality": "skin",
                "ai_diagnosis": "Melanoma",
                "confidence": 0.88, "scan_date": datetime(2024, 2, 1),
            }
        return {
            "scan_id": prev_id, "modality": "skin",
            "ai_diagnosis": "Normal skin",
            "confidence": 0.95, "scan_date": datetime(2024, 1, 1),
        }

    config = _setup_mock_config(user_id, fetchrow_side_effect=side_effect)
    res = await calculate_temporal_progression.ainvoke(
        {"current_scan_id": curr_id, "previous_scan_id": prev_id}, config=config
    )
    assert res["direction"] == "worsening"


@pytest.mark.asyncio
async def test_skin_dermatofibroma_to_basal_cell_carcinoma_is_changed():
    """Dermatofibroma → Basal cell carcinoma (both abnormal) must be classified as changed."""
    from app.agent.tools.temporal import calculate_temporal_progression

    user_id = str(uuid.uuid4())
    curr_id = str(uuid.uuid4())
    prev_id = str(uuid.uuid4())

    def side_effect(query, *args):
        if curr_id in str(args):
            return {
                "scan_id": curr_id, "modality": "skin",
                "ai_diagnosis": "Basal cell carcinoma",
                "confidence": 0.85, "scan_date": datetime(2024, 2, 1),
            }
        return {
            "scan_id": prev_id, "modality": "skin",
            "ai_diagnosis": "Dermatofibroma",
            "confidence": 0.80, "scan_date": datetime(2024, 1, 1),
        }

    config = _setup_mock_config(user_id, fetchrow_side_effect=side_effect)
    res = await calculate_temporal_progression.ainvoke(
        {"current_scan_id": curr_id, "previous_scan_id": prev_id}, config=config
    )
    assert res["direction"] == "changed"


@pytest.mark.asyncio
async def test_skin_normal_skin_to_normal_skin_is_unchanged():
    """Normal skin → Normal skin must be classified as unchanged."""
    from app.agent.tools.temporal import calculate_temporal_progression

    user_id = str(uuid.uuid4())
    curr_id = str(uuid.uuid4())
    prev_id = str(uuid.uuid4())

    def side_effect(query, *args):
        if curr_id in str(args):
            return {
                "scan_id": curr_id, "modality": "skin",
                "ai_diagnosis": "Normal skin",
                "confidence": 0.97, "scan_date": datetime(2024, 2, 1),
            }
        return {
            "scan_id": prev_id, "modality": "skin",
            "ai_diagnosis": "Normal skin",
            "confidence": 0.95, "scan_date": datetime(2024, 1, 1),
        }

    config = _setup_mock_config(user_id, fetchrow_side_effect=side_effect)
    res = await calculate_temporal_progression.ainvoke(
        {"current_scan_id": curr_id, "previous_scan_id": prev_id}, config=config
    )
    assert res["direction"] == "unchanged"
