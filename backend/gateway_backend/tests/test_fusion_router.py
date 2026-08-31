"""Tests for POST /api/v1/fusion/fuse.

Test style matches test_scans_router.py: explicit side_effect or explicit
structured return_value on every mock — never a bare AsyncMock for a failure
path.  Pool/connection mocking uses the same MockAcquireContextManager pattern.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.security import get_current_user

client = TestClient(app)
FAKE_USER_ID = "ff46e7d4-df9c-406f-be0c-987537a1b8a3"

URL = "/api/v1/fusion/fuse"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockAcquireContextManager:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


def _make_row(modality: str, diagnosis: str, confidence: float) -> Dict[str, Any]:
    """Build a dict that asyncpg fetch rows support key access on."""
    return {
        "scan_id": uuid.uuid4(),
        "modality": modality,
        "ai_diagnosis": diagnosis,
        "confidence": confidence,
    }


def _make_pool_with_fetchrow(
    *,
    per_modality_map: Optional[Dict[str, Optional[Dict[str, Any]]]] = None,
    fetchrow_side_effect=None,
) -> tuple:
    """Create a mock pool whose conn.fetchrow returns values from per_modality_map.

    per_modality_map: keys are modality strings; values are dicts with
    ai_diagnosis+confidence (or None to simulate no row for that modality).
    """
    pool = MagicMock()
    conn = AsyncMock()

    if fetchrow_side_effect is not None:
        conn.fetchrow.side_effect = fetchrow_side_effect
    elif per_modality_map is not None:
        # fetchrow is called once per modality (cxr, ecg, skin) in order.
        # Return the dict for each modality or None if absent from map.
        results = []
        for mod in ["cxr", "ecg", "skin"]:
            v = per_modality_map.get(mod)
            results.append(v)
        conn.fetchrow.side_effect = results
    else:
        conn.fetchrow.return_value = None

    pool.acquire.return_value = MockAcquireContextManager(conn)
    return pool, conn


def _make_pool_with_fetch(
    *,
    fetch_return: Optional[List[Dict[str, Any]]] = None,
    fetch_side_effect=None,
) -> tuple:
    """Create a mock pool whose conn.fetch returns a list of rows."""
    pool = MagicMock()
    conn = AsyncMock()

    if fetch_side_effect is not None:
        conn.fetch.side_effect = fetch_side_effect
    elif fetch_return is not None:
        conn.fetch.return_value = fetch_return
    else:
        conn.fetch.return_value = []

    pool.acquire.return_value = MockAcquireContextManager(conn)
    return pool, conn


# ---------------------------------------------------------------------------
# Auth + fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def override_auth():
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER_ID
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def app_state_override():
    original_pool = getattr(app.state, "db_pool", None)
    yield
    app.state.db_pool = original_pool


# ---------------------------------------------------------------------------
# Test 1: Two abnormal modalities above threshold → CRITICAL + critical_alert
# ---------------------------------------------------------------------------


def test_two_abnormal_modalities_critical(app_state_override):
    """Two abnormal scans with confidences that produce a score >= 0.85
    must yield risk_level='CRITICAL' and critical_alert=True."""
    # CXR: Enlarged Cardiomediastinum at 1.0 → weight 1.2
    # ECG: MI at 1.0 → weight 1.5
    # score = (1.0*1.2 + 1.0*1.5) / (1.2+1.5) = 2.7/2.7 = 1.0 → CRITICAL
    cxr_id = str(uuid.uuid4())
    ecg_id = str(uuid.uuid4())

    pool, conn = _make_pool_with_fetch(
        fetch_return=[
            _make_row("cxr", "Enlarged Cardiomediastinum", 1.0),
            _make_row("ecg", "MI", 1.0),
        ]
    )
    app.state.db_pool = pool

    resp = client.post(URL, json={"selected_scan_ids": [cxr_id, ecg_id]})
    assert resp.status_code == 200
    data = resp.json()

    assert data["fusion_performed"] is True
    assert data["critical_alert"] is True
    assert data["risk_level"] == "CRITICAL"
    assert data["overall_risk_score"] == 1.0


# ---------------------------------------------------------------------------
# Test 2: Boundary correctness — score at exactly 0.30 and 0.60
# ---------------------------------------------------------------------------


def test_risk_level_boundary_at_0_30(app_state_override):
    """A score of exactly 0.30 must be MODERATE (inclusive lower bound)."""
    from app.services.fusion_engine import compute_risk_level
    assert compute_risk_level(0.30) == "MODERATE"


def test_risk_level_boundary_at_0_60(app_state_override):
    """A score of exactly 0.60 must be HIGH (inclusive lower bound)."""
    from app.services.fusion_engine import compute_risk_level
    assert compute_risk_level(0.60) == "HIGH"


def test_risk_level_below_0_30(app_state_override):
    """A score below 0.30 must be LOW."""
    from app.services.fusion_engine import compute_risk_level
    assert compute_risk_level(0.29) == "LOW"


def test_risk_level_below_0_60(app_state_override):
    """A score of 0.59 must be MODERATE, not HIGH."""
    from app.services.fusion_engine import compute_risk_level
    assert compute_risk_level(0.59) == "MODERATE"


def test_risk_level_at_0_85(app_state_override):
    """A score of exactly 0.85 must be CRITICAL."""
    from app.services.fusion_engine import compute_risk_level
    assert compute_risk_level(0.85) == "CRITICAL"


# ---------------------------------------------------------------------------
# Test 3: fusion_performed=False → risk_level is null, critical_alert=False
# ---------------------------------------------------------------------------


def test_single_modality_no_risk_level(app_state_override):
    """A single-modality result must have risk_level=null and critical_alert=False,
    even if the confidence is very high.  B22 invariant — must not be broken."""
    cxr_id = str(uuid.uuid4())

    pool, _ = _make_pool_with_fetch(
        fetch_return=[
            _make_row("cxr", "Enlarged Cardiomediastinum", 0.99),
        ]
    )
    app.state.db_pool = pool

    resp = client.post(URL, json={"selected_scan_ids": [cxr_id]})
    assert resp.status_code == 200
    data = resp.json()

    assert data["fusion_performed"] is False
    assert data["risk_level"] is None
    assert data["critical_alert"] is False


# ---------------------------------------------------------------------------
# Test 4: selected_scan_ids omitted → auto-selects most recent per modality
# ---------------------------------------------------------------------------


def test_autoselect_queries_per_modality(app_state_override):
    """When selected_scan_ids is omitted, the endpoint issues per-modality
    fetchrow queries.  Assert on the query text itself, not just the response."""
    cxr_row = {"ai_diagnosis": "No Finding", "confidence": 0.95}
    ecg_row = None  # no ECG scan for this user
    skin_row = None

    pool, conn = _make_pool_with_fetchrow(
        per_modality_map={"cxr": cxr_row, "ecg": ecg_row, "skin": skin_row}
    )
    app.state.db_pool = pool

    resp = client.post(URL, json={})
    assert resp.status_code == 200

    # Three fetchrow calls (one per modality)
    assert conn.fetchrow.call_count == 3

    # First call must reference cxr and include tenant scoping
    first_call_sql: str = conn.fetchrow.call_args_list[0].args[0]
    assert "user_id = $1" in first_call_sql
    assert "modality = $2" in first_call_sql
    assert "ORDER BY scan_date DESC" in first_call_sql
    assert "LIMIT 1" in first_call_sql

    # Modality arguments in positional order: cxr, ecg, skin
    assert conn.fetchrow.call_args_list[0].args[2] == "cxr"
    assert conn.fetchrow.call_args_list[1].args[2] == "ecg"
    assert conn.fetchrow.call_args_list[2].args[2] == "skin"


# ---------------------------------------------------------------------------
# Test 5: Duplicate modality in selected_scan_ids → rejected with message
# ---------------------------------------------------------------------------


def test_duplicate_modality_rejected(app_state_override):
    """Two scans of the same modality in selected_scan_ids must be rejected
    with a descriptive message, not silently resolved."""
    cxr_id1 = str(uuid.uuid4())
    cxr_id2 = str(uuid.uuid4())

    pool, _ = _make_pool_with_fetch(
        fetch_return=[
            _make_row("cxr", "Enlarged Cardiomediastinum", 0.91),
            _make_row("cxr", "No Finding", 0.80),
        ]
    )
    app.state.db_pool = pool

    resp = client.post(URL, json={"selected_scan_ids": [cxr_id1, cxr_id2]})
    assert resp.status_code == 200
    data = resp.json()

    assert data["message"] is not None
    assert "cxr" in data["message"].lower()
    # Must not appear as a normal gauge payload
    assert data["fusion_performed"] is False
    assert data["risk_level"] is None


# ---------------------------------------------------------------------------
# Test 6: Scan belonging to another user is not returned
# ---------------------------------------------------------------------------


def test_other_user_scan_not_returned(app_state_override):
    """The query must be scoped to user_id = $2; another user's scan_id
    produces an empty result, not cross-tenant leakage."""
    other_user_scan_id = str(uuid.uuid4())

    # Simulate DB returning no rows for this user (the scan_id belongs to another user)
    pool, conn = _make_pool_with_fetch(fetch_return=[])
    app.state.db_pool = pool

    resp = client.post(URL, json={"selected_scan_ids": [other_user_scan_id]})
    assert resp.status_code == 200
    data = resp.json()

    # Must get the no-scans message, not a fabricated gauge payload
    assert data["message"] is not None
    assert data["modality_risks"] == []

    # Confirm user_id is in the query params (tenant isolation)
    fetch_query: str = conn.fetch.call_args.args[0]
    assert "user_id = $2" in fetch_query


# ---------------------------------------------------------------------------
# Test 7: Out-of-range confidence (>1.0) → excluded into unscored
# ---------------------------------------------------------------------------


def test_out_of_range_confidence_excluded(app_state_override):
    """A scan with confidence > 1.0 must appear in unscored, not in
    modality_risks, and must not be clamped to 1.0."""
    cxr_id = str(uuid.uuid4())
    skin_id = str(uuid.uuid4())

    pool, _ = _make_pool_with_fetch(
        fetch_return=[
            _make_row("cxr", "Enlarged Cardiomediastinum", 1.5),   # out-of-range
            _make_row("skin", "Melanocytic nevi", 0.90),
        ]
    )
    app.state.db_pool = pool

    resp = client.post(URL, json={"selected_scan_ids": [cxr_id, skin_id]})
    assert resp.status_code == 200
    data = resp.json()

    modality_names = [m["modality"] for m in data["modality_risks"]]
    assert "cxr" not in modality_names
    assert "skin" in modality_names

    assert any("cxr" in u and "outside" in u for u in data["unscored"])


# ---------------------------------------------------------------------------
# Test 8: Unrecognised label → excluded into unscored
# ---------------------------------------------------------------------------


def test_unrecognised_label_excluded(app_state_override):
    """A scan with an unrecognised ai_diagnosis must appear in unscored,
    not in modality_risks."""
    cxr_id = str(uuid.uuid4())
    skin_id = str(uuid.uuid4())

    pool, _ = _make_pool_with_fetch(
        fetch_return=[
            _make_row("cxr", "COMPLETELY_UNKNOWN_LABEL_XYZ", 0.80),
            _make_row("skin", "Melanocytic nevi", 0.70),
        ]
    )
    app.state.db_pool = pool

    resp = client.post(URL, json={"selected_scan_ids": [cxr_id, skin_id]})
    assert resp.status_code == 200
    data = resp.json()

    modality_names = [m["modality"] for m in data["modality_risks"]]
    assert "cxr" not in modality_names
    assert "skin" in modality_names

    assert any("Unrecognised label" in u for u in data["unscored"])


# ---------------------------------------------------------------------------
# Test 9: findings_summary — exact string for demo pair
# ---------------------------------------------------------------------------


def test_findings_summary_exact_string(app_state_override):
    """CXR Enlarged Cardiomediastinum 0.9173 + skin Melanocytic nevi 0.9953
    must produce the exact findings_summary string from the spec, and
    overall_risk_score must equal 0.5003, risk_level 'MODERATE',
    critical_alert False — verified through this endpoint, not just the tool."""
    cxr_id = str(uuid.uuid4())
    skin_id = str(uuid.uuid4())

    pool, _ = _make_pool_with_fetch(
        fetch_return=[
            _make_row("cxr", "Enlarged Cardiomediastinum", 0.9173),
            _make_row("skin", "Melanocytic nevi", 0.9953),
        ]
    )
    app.state.db_pool = pool

    resp = client.post(URL, json={"selected_scan_ids": [cxr_id, skin_id]})
    assert resp.status_code == 200
    data = resp.json()

    # Score: (0.9173*1.2 + 0.0*1.0) / (1.2+1.0) = 1.10076/2.2 = 0.50034... → 0.5003
    assert data["overall_risk_score"] == 0.5003
    assert data["risk_level"] == "MODERATE"
    assert data["critical_alert"] is False
    assert data["fusion_performed"] is True

    # Exact findings_summary string
    expected_summary = (
        "CXR: Enlarged Cardiomediastinum (abnormal, 91.7%). "
        "SKIN: Melanocytic nevi (normal, 99.5%)."
    )
    assert data["findings_summary"] == expected_summary

    # Assert it's the literal string — not just non-empty
    assert len(data["findings_summary"]) == len(expected_summary)


# ---------------------------------------------------------------------------
# Test 10: Database failure → 503, not empty or zeroed payload
# ---------------------------------------------------------------------------


def test_db_failure_raises_503(app_state_override):
    """A PostgresError during the query must produce a 503, not an empty
    or zeroed response payload."""
    pool, _ = _make_pool_with_fetch(
        fetch_side_effect=asyncpg.PostgresError("Connection lost")
    )
    app.state.db_pool = pool

    resp = client.post(URL, json={"selected_scan_ids": [str(uuid.uuid4())]})
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Database query failed"


def test_db_failure_autoselect_raises_503(app_state_override):
    """A PostgresError during auto-select must also produce a 503."""
    pool, conn = _make_pool_with_fetchrow(
        fetchrow_side_effect=asyncpg.PostgresError("DB down")
    )
    app.state.db_pool = pool

    resp = client.post(URL, json={})
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Database query failed"


# ---------------------------------------------------------------------------
# Test 11: No scans at all → message-style response, not gauge-shaped empty
# ---------------------------------------------------------------------------


def test_no_scans_returns_message(app_state_override):
    """When no scans exist for the caller, the response must carry a message
    field, not a zeroed gauge payload pretending to be valid data."""
    pool, _ = _make_pool_with_fetch(fetch_return=[])
    app.state.db_pool = pool

    resp = client.post(URL, json={"selected_scan_ids": [str(uuid.uuid4())]})
    assert resp.status_code == 200
    data = resp.json()

    assert data["message"] is not None
    assert "No valid scans" in data["message"]
    assert data["modality_risks"] == []
    assert data["fusion_performed"] is False


def test_no_scans_autoselect_returns_message(app_state_override):
    """Auto-select with no scans must also return the message-style response."""
    pool, _ = _make_pool_with_fetchrow(
        per_modality_map={"cxr": None, "ecg": None, "skin": None}
    )
    app.state.db_pool = pool

    resp = client.post(URL, json={})
    assert resp.status_code == 200
    data = resp.json()

    assert data["message"] is not None
    assert "No recent scans" in data["message"]
    assert data["modality_risks"] == []
    assert data["fusion_performed"] is False


# ---------------------------------------------------------------------------
# Test 12: Invalid UUID in selected_scan_ids → 422
# ---------------------------------------------------------------------------


def test_invalid_uuid_rejected(app_state_override):
    """A non-UUID string in selected_scan_ids must produce 422."""
    pool, _ = _make_pool_with_fetch(fetch_return=[])
    app.state.db_pool = pool

    resp = client.post(URL, json={"selected_scan_ids": ["not-a-uuid"]})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Test 13: Unscored modalities do NOT also appear in modality_risks
# ---------------------------------------------------------------------------


def test_unscored_not_in_modality_risks(app_state_override):
    """A modality in unscored must not appear in modality_risks — no
    duplicate/conflicting representation across the two lists."""
    cxr_id = str(uuid.uuid4())
    ecg_id = str(uuid.uuid4())

    pool, _ = _make_pool_with_fetch(
        fetch_return=[
            _make_row("cxr", "Enlarged Cardiomediastinum", 2.0),  # out-of-range → unscored
            _make_row("ecg", "MI", 0.88),                          # valid → scored
        ]
    )
    app.state.db_pool = pool

    resp = client.post(URL, json={"selected_scan_ids": [cxr_id, ecg_id]})
    assert resp.status_code == 200
    data = resp.json()

    modality_names = [m["modality"] for m in data["modality_risks"]]
    assert "cxr" not in modality_names
    assert "ecg" in modality_names
    assert any("cxr" in u for u in data["unscored"])

# ---------------------------------------------------------------------------
# Test 14: Clinical correlation with LLM
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_generate_hedged_text():
    with patch("app.api.fusion_router.generate_hedged_text", new_callable=AsyncMock) as m:
        m.return_value = "Correlation text."
        yield m

def test_clinical_correlation_2_abnormal(app_state_override, mock_generate_hedged_text):
    cxr_id = str(uuid.uuid4())
    ecg_id = str(uuid.uuid4())

    pool, _ = _make_pool_with_fetch(
        fetch_return=[
            _make_row("cxr", "Enlarged Cardiomediastinum", 0.90),
            _make_row("ecg", "MI", 0.90),
        ]
    )
    app.state.db_pool = pool

    resp = client.post(URL, json={"selected_scan_ids": [cxr_id, ecg_id]})
    assert resp.status_code == 200
    data = resp.json()

    assert data["fusion_performed"] is True
    assert data["clinical_correlation"] == "Correlation text."
    mock_generate_hedged_text.assert_called_once()


def test_clinical_correlation_1_abnormal_1_normal(app_state_override, mock_generate_hedged_text):
    cxr_id = str(uuid.uuid4())
    ecg_id = str(uuid.uuid4())

    pool, _ = _make_pool_with_fetch(
        fetch_return=[
            _make_row("cxr", "Enlarged Cardiomediastinum", 0.90),
            _make_row("ecg", "Normal", 0.90),
        ]
    )
    app.state.db_pool = pool

    resp = client.post(URL, json={"selected_scan_ids": [cxr_id, ecg_id]})
    assert resp.status_code == 200
    data = resp.json()

    assert data["clinical_correlation"] is None
    mock_generate_hedged_text.assert_not_called()


def test_clinical_correlation_3_abnormal(app_state_override, mock_generate_hedged_text):
    cxr_id = str(uuid.uuid4())
    ecg_id = str(uuid.uuid4())
    skin_id = str(uuid.uuid4())

    pool, _ = _make_pool_with_fetch(
        fetch_return=[
            _make_row("cxr", "Enlarged Cardiomediastinum", 0.90),
            _make_row("ecg", "MI", 0.90),
            _make_row("skin", "Melanoma", 0.90),
        ]
    )
    app.state.db_pool = pool

    resp = client.post(URL, json={"selected_scan_ids": [cxr_id, ecg_id, skin_id]})
    assert resp.status_code == 200
    data = resp.json()

    assert data["clinical_correlation"] == "Correlation text."
    mock_generate_hedged_text.assert_called_once()
    prompt = mock_generate_hedged_text.call_args.args[0]
    assert "CXR: Enlarged Cardiomediastinum" in prompt
    assert "ECG: MI" in prompt
    assert "SKIN: Melanoma" in prompt


def test_clinical_correlation_llm_failure_does_not_affect_gauge(app_state_override, mock_generate_hedged_text):
    cxr_id = str(uuid.uuid4())
    ecg_id = str(uuid.uuid4())

    pool, _ = _make_pool_with_fetch(
        fetch_return=[
            _make_row("cxr", "Enlarged Cardiomediastinum", 1.0),
            _make_row("ecg", "MI", 1.0),
        ]
    )
    app.state.db_pool = pool

    # Simulate LLM returning None (or raising, but our LLM helper catches and returns None)
    mock_generate_hedged_text.return_value = None

    resp = client.post(URL, json={"selected_scan_ids": [cxr_id, ecg_id]})
    assert resp.status_code == 200
    data = resp.json()

    assert data["clinical_correlation"] is None
    assert data["fusion_performed"] is True
    assert data["critical_alert"] is True
    assert data["risk_level"] == "CRITICAL"
    assert data["overall_risk_score"] == 1.0
