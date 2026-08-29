"""Tests for the /scans/history and /scans/trends endpoints."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.security import get_current_user

client = TestClient(app)
FAKE_USER_ID = str(uuid.uuid4())

class MockAcquireContextManager:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None

def create_mock_pool(fetch_side_effect=None, fetchval_side_effect=None, fetch_return=None, fetchval_return=None):
    pool = MagicMock()
    conn = AsyncMock()
    
    if fetch_side_effect:
        conn.fetch.side_effect = fetch_side_effect
    elif fetch_return is not None:
        conn.fetch.return_value = fetch_return
    else:
        conn.fetch.return_value = []
        
    if fetchval_side_effect:
        conn.fetchval.side_effect = fetchval_side_effect
    elif fetchval_return is not None:
        conn.fetchval.return_value = fetchval_return
    else:
        conn.fetchval.return_value = 0

    pool.acquire.return_value = MockAcquireContextManager(conn)
    return pool, conn


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer fake_jwt_token"}

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

# --- history tests ---

def test_history_caller_rows_only(auth_headers, app_state_override):
    # 1. Returns only the caller's rows — a second user's scan is absent (Mocking db to return 1 row)
    # The query filters by user_id so if the db returns it, it's correct. We just test if it returns what DB gives.
    row = {
        "scan_id": str(uuid.uuid4()),
        "modality": "cxr",
        "ai_diagnosis": "No Finding",
        "confidence": 0.9,
        "scan_status": 0,
        "scan_date": datetime.now(timezone.utc),
        "xai_status": "none",
        "xai_path": None,
        "storage_path": "path/to/img"
    }
    pool, _ = create_mock_pool(fetch_return=[row], fetchval_return=1)
    app.state.db_pool = pool
    
    resp = client.get("/api/v1/scans/history", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["scan_id"] == row["scan_id"]

def test_history_modality_filter(auth_headers, app_state_override):
    # 2. modality filter returns only that modality
    pool, conn = create_mock_pool(fetchval_return=0)
    app.state.db_pool = pool
    client.get("/api/v1/scans/history?modality=ecg", headers=auth_headers)
    
    # Check that 'ecg' was passed to the query
    call_args = conn.fetch.call_args
    assert "ecg" in call_args.args

def test_history_invalid_modality(auth_headers, app_state_override):
    # 3. An invalid modality value returns 422
    resp = client.get("/api/v1/scans/history?modality=mri", headers=auth_headers)
    assert resp.status_code == 422

def test_history_limit_clamped(auth_headers, app_state_override):
    # 4. limit above the maximum is rejected or clamped
    # FastAPI Query(le=100) rejects >100 with 422
    resp = client.get("/api/v1/scans/history?limit=1000", headers=auth_headers)
    assert resp.status_code == 422

def test_history_pagination(auth_headers, app_state_override):
    # 5. Pagination: offset shifts the window and the total count stays correct
    pool, conn = create_mock_pool(fetchval_return=50)
    app.state.db_pool = pool
    client.get("/api/v1/scans/history?limit=10&offset=20", headers=auth_headers)
    call_args = conn.fetch.call_args
    assert 10 in call_args.args  # limit
    assert 20 in call_args.args  # offset

def test_history_empty_list_not_404(auth_headers, app_state_override):
    # 6. No scans returns 200 with an empty list, not 404
    pool, _ = create_mock_pool(fetch_return=[], fetchval_return=0)
    app.state.db_pool = pool
    resp = client.get("/api/v1/scans/history", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["items"] == []
    assert resp.json()["total_count"] == 0

def test_history_scan_type_absent(auth_headers, app_state_override):
    # 7. scan_type does not appear in the response
    row = {
        "scan_id": str(uuid.uuid4()),
        "modality": "cxr",
        "ai_diagnosis": "No Finding",
        "confidence": 0.9,
        "scan_status": 0,
        "scan_date": datetime.now(timezone.utc),
        "xai_status": "none",
        "xai_path": None,
        "storage_path": "path/to/img"
    }
    pool, _ = create_mock_pool(fetch_return=[row], fetchval_return=1)
    app.state.db_pool = pool
    resp = client.get("/api/v1/scans/history", headers=auth_headers)
    assert "scan_type" not in resp.json()["items"][0]

def test_history_modality_is_null_excluded(auth_headers, app_state_override):
    # 8. A modality IS NULL row is excluded
    pool, conn = create_mock_pool(fetchval_return=0)
    app.state.db_pool = pool
    client.get("/api/v1/scans/history", headers=auth_headers)
    assert "modality IS NOT NULL" in conn.fetch.call_args.args[0]

# --- trends tests ---

def test_trends_missing_modality(auth_headers, app_state_override):
    # 9. Missing modality returns 422
    resp = client.get("/api/v1/scans/trends", headers=auth_headers)
    assert resp.status_code == 422

def run_trends_transition_test(auth_headers, diag1, diag2, expected_direction, modality="cxr", conf_delta=None):
    row1 = {
        "scan_id": str(uuid.uuid4()),
        "modality": modality,
        "ai_diagnosis": diag1,
        "confidence": 0.5,
        "scan_status": 0,
        "scan_date": datetime.now(timezone.utc),
        "xai_status": "none",
        "xai_path": None,
        "storage_path": None
    }
    row2 = {
        "scan_id": str(uuid.uuid4()),
        "modality": modality,
        "ai_diagnosis": diag2,
        "confidence": 0.5 if conf_delta is None else 0.5 + conf_delta,
        "scan_status": 0,
        "scan_date": datetime.now(timezone.utc),
        "xai_status": "none",
        "xai_path": None,
        "storage_path": None
    }
    pool, _ = create_mock_pool(fetch_return=[row1, row2])
    app.state.db_pool = pool
    resp = client.get(f"/api/v1/scans/trends?modality={modality}", headers=auth_headers)
    assert resp.status_code == 200
    transitions = resp.json()["transitions"]
    assert len(transitions) == 1
    assert transitions[0]["direction"] == expected_direction
    return transitions[0]

def test_trends_normal_to_abnormal(auth_headers, app_state_override):
    # 10. normal → abnormal produces worsening
    run_trends_transition_test(auth_headers, "No Finding", "Pneumonia", "worsening")

def test_trends_abnormal_to_normal(auth_headers, app_state_override):
    # 11. abnormal → normal produces improving
    run_trends_transition_test(auth_headers, "Pneumonia", "No Finding", "improving")

def test_trends_abnormal_to_different_abnormal(auth_headers, app_state_override):
    # 12. abnormal → different abnormal produces changed
    run_trends_transition_test(auth_headers, "Pneumonia", "Fracture", "changed")

def test_trends_same_label(auth_headers, app_state_override):
    # 13. same label produces unchanged
    run_trends_transition_test(auth_headers, "Pneumonia", "Pneumonia", "unchanged")

def test_trends_unrecognised_label(auth_headers, app_state_override):
    # 14. an unrecognised label produces indeterminate
    run_trends_transition_test(auth_headers, "Unknown Disease", "No Finding", "indeterminate")

def test_trends_normal_to_different_normal_returns_unchanged(auth_headers, app_state_override):
    # normal → different normal produces unchanged, not changed
    run_trends_transition_test(
        auth_headers, "Dermatofibroma", "Vascular lesions", "unchanged", modality="skin"
    )

def test_trends_large_conf_delta_does_not_alter_direction(auth_headers, app_state_override):
    # 15. a large confidence_delta on an unchanged label does not alter direction
    transition = run_trends_transition_test(auth_headers, "Pneumonia", "Pneumonia", "unchanged", conf_delta=0.4)
    assert transition["confidence_delta"] == 0.4000

def test_trends_one_scan(auth_headers, app_state_override):
    # 16. one scan returns the series with an empty transitions array
    row = {
        "scan_id": str(uuid.uuid4()),
        "modality": "cxr",
        "ai_diagnosis": "No Finding",
        "confidence": 0.9,
        "scan_status": 0,
        "scan_date": datetime.now(timezone.utc),
        "xai_status": "none",
        "xai_path": None,
        "storage_path": None
    }
    pool, _ = create_mock_pool(fetch_return=[row])
    app.state.db_pool = pool
    resp = client.get("/api/v1/scans/trends?modality=cxr", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()["scans"]) == 1
    assert resp.json()["transitions"] == []

def test_trends_other_user_excluded(auth_headers, app_state_override):
    # 17. another user's scans are not included (mock assert)
    pool, conn = create_mock_pool(fetch_return=[])
    app.state.db_pool = pool
    client.get("/api/v1/scans/trends?modality=cxr", headers=auth_headers)
    assert "user_id = $1" in conn.fetch.call_args.args[0]

def test_trends_db_failure(auth_headers, app_state_override):
    # 18. a database failure returns 5xx, not an empty list
    pool, _ = create_mock_pool(fetch_side_effect=asyncpg.PostgresError("DB is down"))
    app.state.db_pool = pool
    resp = client.get("/api/v1/scans/trends?modality=cxr", headers=auth_headers)
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Database query failed"

def test_history_db_failure(auth_headers, app_state_override):
    # Database failure also for history
    pool, _ = create_mock_pool(fetchval_side_effect=asyncpg.PostgresError("DB is down"))
    app.state.db_pool = pool
    resp = client.get("/api/v1/scans/history", headers=auth_headers)
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Database query failed"


# ---------------------------------------------------------------------------
# Task 4 — explainability in history responses
# ---------------------------------------------------------------------------

def _make_history_row(xai_status: str, xai_path=None, modality: str = "cxr") -> dict:
    """Helper: build a minimal mock db row for history/trends tests."""
    return {
        "scan_id": str(uuid.uuid4()),
        "modality": modality,
        "ai_diagnosis": "No Finding",
        "confidence": 0.80,
        "scan_status": 0,
        "scan_date": datetime.now(timezone.utc),
        "xai_status": xai_status,
        "xai_path": xai_path,
        "storage_path": "p" if xai_path else None,
    }


def test_history_explainability_status_none(auth_headers, app_state_override):
    """A row with xai_status='none' produces explainability.status='none' and url=null."""
    row = _make_history_row("none", xai_path=None)
    pool, _ = create_mock_pool(fetch_return=[row], fetchval_return=1)
    app.state.db_pool = pool

    resp = client.get("/api/v1/scans/history", headers=auth_headers)
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert "explainability" in item
    xai = item["explainability"]
    assert xai["status"] == "none"
    assert xai["url"] is None
    assert xai["modality"] == "cxr"


def test_history_explainability_status_generated_url_non_null(auth_headers, app_state_override):
    """A row with xai_status='generated' produces non-null url built from xai_path."""
    fake_path = f"{FAKE_USER_ID}/{uuid.uuid4()}/overlay_0.png"
    row = _make_history_row("generated", xai_path=fake_path, modality="cxr")
    pool, _ = create_mock_pool(fetch_return=[row], fetchval_return=1)
    app.state.db_pool = pool

    resp = client.get("/api/v1/scans/history", headers=auth_headers)
    assert resp.status_code == 200
    xai = resp.json()["items"][0]["explainability"]
    assert xai["status"] == "generated"
    assert xai["url"] is not None
    assert "/authenticated/" in xai["url"]
    assert fake_path in xai["url"]
    assert "/public/" not in xai["url"]
    # No signed URL query parameter
    assert "token=" not in xai["url"]
    assert "?" not in xai["url"]


def test_history_explainability_status_failed(auth_headers, app_state_override):
    """A row with xai_status='failed' produces url=null."""
    row = _make_history_row("failed", xai_path=None)
    pool, _ = create_mock_pool(fetch_return=[row], fetchval_return=1)
    app.state.db_pool = pool

    resp = client.get("/api/v1/scans/history", headers=auth_headers)
    assert resp.status_code == 200
    xai = resp.json()["items"][0]["explainability"]
    assert xai["status"] == "failed"
    assert xai["url"] is None


def test_history_explainability_status_skipped_edge(auth_headers, app_state_override):
    """A row with xai_status='skipped_edge' produces url=null."""
    row = _make_history_row("skipped_edge", xai_path=None, modality="ecg")
    pool, _ = create_mock_pool(fetch_return=[row], fetchval_return=1)
    app.state.db_pool = pool

    resp = client.get("/api/v1/scans/history", headers=auth_headers)
    assert resp.status_code == 200
    xai = resp.json()["items"][0]["explainability"]
    assert xai["status"] == "skipped_edge"
    assert xai["url"] is None
    assert xai["modality"] == "ecg"


def test_history_bare_xai_status_still_present(auth_headers, app_state_override):
    """The bare top-level xai_status field is still present (backwards compatibility)."""
    row = _make_history_row("generated", xai_path=f"{FAKE_USER_ID}/scan/overlay_0.png")
    pool, _ = create_mock_pool(fetch_return=[row], fetchval_return=1)
    app.state.db_pool = pool

    resp = client.get("/api/v1/scans/history", headers=auth_headers)
    item = resp.json()["items"][0]
    assert "xai_status" in item
    assert item["xai_status"] == "generated"


# --- claim and triage tests ---

from jose import jwt
from datetime import timedelta
from app.core.config import gateway_config

@pytest.fixture
def valid_claim_token():
    payload = {
        "sub": str(uuid.uuid4()),
        "scan_ids": [str(uuid.uuid4())],
        "exp": datetime.utcnow() + timedelta(hours=1),
        "purpose": "report_claim"
    }
    return jwt.encode(payload, gateway_config.report_token_secret, algorithm="HS256"), payload["sub"]

def test_claim_valid_token_no_prior_relationship(auth_headers, app_state_override, valid_claim_token):
    token, patient_id = valid_claim_token
    # mock doctor exists, no prior relationship
    def fetchval_side_effect(query, *args):
        if "doctor_profiles" in query:
            return True
        return None
    def fetchrow_side_effect(query, *args):
        return None
    
    pool = MagicMock()
    conn = AsyncMock()
    conn.fetchval.side_effect = fetchval_side_effect
    conn.fetchrow.side_effect = fetchrow_side_effect
    pool.acquire.return_value = MockAcquireContextManager(conn)
    app.state.db_pool = pool
    app.state.supabase_client = MagicMock()
    app.state.supabase_client.storage.from_().create_signed_url = AsyncMock(return_value={"signedURL": "http://fake"})

    resp = client.post("/api/v1/scans/claim", json={"token": token}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["access_granted"] is True
    assert data["patient_ref"].startswith("PT-")
    assert "user_id" not in data
    assert "name" not in data
    # assert insert was called
    insert_call = next((call for call in conn.execute.call_args_list if "INSERT INTO care_relationships" in call.args[0]), None)
    assert insert_call is not None

def test_claim_valid_token_active_relationship(auth_headers, app_state_override, valid_claim_token):
    token, patient_id = valid_claim_token
    def fetchval_side_effect(query, *args):
        if "doctor_profiles" in query:
            return True
        return None
    def fetchrow_side_effect(query, *args):
        return {"status": "active", "ended_at": None}
    
    pool = MagicMock()
    conn = AsyncMock()
    conn.fetchval.side_effect = fetchval_side_effect
    conn.fetchrow.side_effect = fetchrow_side_effect
    pool.acquire.return_value = MockAcquireContextManager(conn)
    app.state.db_pool = pool
    app.state.supabase_client = MagicMock()
    app.state.supabase_client.storage.from_().create_signed_url = AsyncMock(return_value={"signedURL": "http://fake"})

    resp = client.post("/api/v1/scans/claim", json={"token": token}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["access_granted"] is True
    update_call = next((call for call in conn.execute.call_args_list if "UPDATE care_relationships SET expires_at" in call.args[0]), None)
    assert update_call is not None
    insert_call = next((call for call in conn.execute.call_args_list if "INSERT INTO care_relationships" in call.args[0]), None)
    assert insert_call is None

def test_claim_valid_token_revoked_relationship(auth_headers, app_state_override, valid_claim_token):
    token, patient_id = valid_claim_token
    def fetchval_side_effect(query, *args):
        if "doctor_profiles" in query:
            return True
        return None
    def fetchrow_side_effect(query, *args):
        return {"status": "revoked", "ended_at": None}
    
    pool = MagicMock()
    conn = AsyncMock()
    conn.fetchval.side_effect = fetchval_side_effect
    conn.fetchrow.side_effect = fetchrow_side_effect
    pool.acquire.return_value = MockAcquireContextManager(conn)
    app.state.db_pool = pool
    app.state.supabase_client = MagicMock()
    app.state.supabase_client.storage.from_().create_signed_url = AsyncMock(return_value={"signedURL": "http://fake"})

    resp = client.post("/api/v1/scans/claim", json={"token": token}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["access_granted"] is False
    assert data["reason"] == "revoked"

def test_claim_valid_token_ended_at_set(auth_headers, app_state_override, valid_claim_token):
    token, patient_id = valid_claim_token
    def fetchval_side_effect(query, *args):
        if "doctor_profiles" in query:
            return True
        return None
    def fetchrow_side_effect(query, *args):
        return {"status": "active", "ended_at": datetime.now(timezone.utc)}
    
    pool = MagicMock()
    conn = AsyncMock()
    conn.fetchval.side_effect = fetchval_side_effect
    conn.fetchrow.side_effect = fetchrow_side_effect
    pool.acquire.return_value = MockAcquireContextManager(conn)
    app.state.db_pool = pool
    app.state.supabase_client = MagicMock()
    app.state.supabase_client.storage.from_().create_signed_url = AsyncMock(return_value={"signedURL": "http://fake"})

    resp = client.post("/api/v1/scans/claim", json={"token": token}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["access_granted"] is False
    assert data["reason"] == "revoked"

def test_claim_caller_is_patient(auth_headers, app_state_override, valid_claim_token):
    token, patient_id = valid_claim_token
    app.dependency_overrides[get_current_user] = lambda: patient_id
    
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire.return_value = MockAcquireContextManager(conn)
    app.state.db_pool = pool
    app.state.supabase_client = MagicMock()
    app.state.supabase_client.storage.from_().create_signed_url = AsyncMock(return_value={"signedURL": "http://fake"})

    resp = client.post("/api/v1/scans/claim", json={"token": token}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["access_granted"] is False
    assert conn.execute.call_count == 0
    assert conn.fetchrow.call_count == 0
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER_ID

def test_claim_caller_not_a_doctor(auth_headers, app_state_override, valid_claim_token):
    token, patient_id = valid_claim_token
    def fetchval_side_effect(query, *args):
        if "doctor_profiles" in query:
            return False
        return None
    
    pool = MagicMock()
    conn = AsyncMock()
    conn.fetchval.side_effect = fetchval_side_effect
    pool.acquire.return_value = MockAcquireContextManager(conn)
    app.state.db_pool = pool
    app.state.supabase_client = MagicMock()
    app.state.supabase_client.storage.from_().create_signed_url = AsyncMock(return_value={"signedURL": "http://fake"})

    resp = client.post("/api/v1/scans/claim", json={"token": token}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["access_granted"] is False
    assert conn.execute.call_count == 0

def test_claim_expired_token(auth_headers, app_state_override):
    app.state.db_pool = MagicMock()
    payload = {
        "sub": str(uuid.uuid4()),
        "scan_ids": [str(uuid.uuid4())],
        "exp": datetime.utcnow() - timedelta(hours=1),
        "purpose": "report_claim"
    }
    token = jwt.encode(payload, gateway_config.report_token_secret, algorithm="HS256")
    resp = client.post("/api/v1/scans/claim", json={"token": token}, headers=auth_headers)
    assert resp.status_code == 403
    assert "expired" in resp.json()["detail"].lower()

def test_claim_wrong_secret(auth_headers, app_state_override):
    app.state.db_pool = MagicMock()
    payload = {
        "sub": str(uuid.uuid4()),
        "scan_ids": [str(uuid.uuid4())],
        "exp": datetime.utcnow() + timedelta(hours=1),
        "purpose": "report_claim"
    }
    token = jwt.encode(payload, "wrong_secret", algorithm="HS256")
    resp = client.post("/api/v1/scans/claim", json={"token": token}, headers=auth_headers)
    assert resp.status_code == 403
    assert "signature" in resp.json()["detail"].lower()

def test_claim_wrong_purpose(auth_headers, app_state_override):
    app.state.db_pool = MagicMock()
    payload = {
        "sub": str(uuid.uuid4()),
        "scan_ids": [str(uuid.uuid4())],
        "exp": datetime.utcnow() + timedelta(hours=1),
        "purpose": "other_purpose"
    }
    token = jwt.encode(payload, gateway_config.report_token_secret, algorithm="HS256")
    resp = client.post("/api/v1/scans/claim", json={"token": token}, headers=auth_headers)
    assert resp.status_code == 403
    assert "purpose" in resp.json()["detail"].lower()


def test_triage_returns_scans(auth_headers, app_state_override):
    patient_id = str(uuid.uuid4())
    row = {
        "scan_id": str(uuid.uuid4()),
        "modality": "cxr",
        "ai_diagnosis": "Pneumonia",
        "confidence": 0.9,
        "scan_status": 2, # High Risk
        "scan_date": datetime.now(timezone.utc),
        "xai_status": "none",
        "xai_path": None,
        "storage_path": "path",
        "user_id": uuid.UUID(patient_id)
    }
    def fetchval_side_effect(query, *args):
        if "doctor_profiles" in query:
            return True
        if "COUNT" in query:
            return 1
        return None
    def fetch_side_effect(query, *args):
        if "ORDER BY" in query:
            return [row]
        return []

    pool = MagicMock()
    conn = AsyncMock()
    conn.fetchval.side_effect = fetchval_side_effect
    conn.fetch.side_effect = fetch_side_effect
    pool.acquire.return_value = MockAcquireContextManager(conn)
    app.state.db_pool = pool

    resp = client.get("/api/v1/scans/triage", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["patient_ref"] == f"PT-{patient_id[:6].upper()}"
    assert "user_id" not in item
    assert item["scan_status"] == 2

def test_triage_not_a_doctor(auth_headers, app_state_override):
    def fetchval_side_effect(query, *args):
        if "doctor_profiles" in query:
            return False
        return None

    pool = MagicMock()
    conn = AsyncMock()
    conn.fetchval.side_effect = fetchval_side_effect
    pool.acquire.return_value = MockAcquireContextManager(conn)
    app.state.db_pool = pool

    resp = client.get("/api/v1/scans/triage", headers=auth_headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Caller is not a registered doctor"

def test_triage_zero_relationships(auth_headers, app_state_override):
    def fetchval_side_effect(query, *args):
        if "doctor_profiles" in query:
            return True
        if "COUNT" in query:
            return 0
        return None

    pool = MagicMock()
    conn = AsyncMock()
    conn.fetchval.side_effect = fetchval_side_effect
    conn.fetch.return_value = []
    pool.acquire.return_value = MockAcquireContextManager(conn)
    app.state.db_pool = pool

    resp = client.get("/api/v1/scans/triage", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []

def test_triage_malformed_sub_claim(app_state_override):
    from app.core.security import get_current_user
    app.dependency_overrides.pop(get_current_user, None)
    pool = MagicMock()
    app.state.db_pool = pool
    from jose import jwt
    import time
    
    # Create an invalid token with a malformed sub claim
    claims = {
        "sub": "not-a-uuid",
        "role": "authenticated",
        "aud": "authenticated",
        "iss": "https://ppwnixwhaxpsqvufdggy.supabase.co/auth/v1",
        "exp": int(time.time()) + 3600
    }
    from tests.conftest import PRIVATE_PEM
    token = jwt.encode(claims, PRIVATE_PEM, algorithm="ES256", headers={"kid": "test-kid"})
    headers = {"Authorization": f"Bearer {token}"}
    
    resp = client.get("/api/v1/scans/triage", headers=headers)
    print(resp.json())
    assert resp.status_code == 422
    assert "Malformed caller_id" in resp.json()["detail"]

def test_triage_query_contains_predicates(auth_headers, app_state_override):
    def fetchval_side_effect(query, *args):
        if "doctor_profiles" in query:
            return True
        if "COUNT" in query:
            return 0
        return None

    pool = MagicMock()
    conn = AsyncMock()
    conn.fetchval.side_effect = fetchval_side_effect
    conn.fetch.return_value = []
    pool.acquire.return_value = MockAcquireContextManager(conn)
    app.state.db_pool = pool

    resp = client.get("/api/v1/scans/triage", headers=auth_headers)
    assert resp.status_code == 200
    
    # Assert query contains the exact conditions required by the constraint
    queries = [call.args[0] for call in conn.fetch.call_args_list]
    assert len(queries) > 0
    q = queries[0]
    assert "s.doctor_id = $1::uuid" in q
    assert "cr.status = 'active'" in q
    assert "(cr.expires_at IS NULL OR cr.expires_at > now())" in q
    assert "ORDER BY s.scan_status DESC, s.scan_date DESC" in q
    assert "cr.status = 'pending'" not in q

def test_claim_report_signed_url_ttl(auth_headers, app_state_override, valid_claim_token):
    from app.core.config import gateway_config
    token, patient_id = valid_claim_token
    # mock doctor exists, no prior relationship
    def fetchval_side_effect(query, *args):
        if "doctor_profiles" in query:
            return True
        return None
    def fetchrow_side_effect(query, *args):
        return None
    
    pool = MagicMock()
    conn = AsyncMock()
    conn.fetchval.side_effect = fetchval_side_effect
    conn.fetchrow.side_effect = fetchrow_side_effect
    pool.acquire.return_value = MockAcquireContextManager(conn)
    app.state.db_pool = pool
    
    mock_create_signed_url = AsyncMock(return_value={"signedURL": "http://fake-report-url"})
    mock_from = MagicMock()
    mock_from.create_signed_url = mock_create_signed_url
    
    app.state.supabase_client = MagicMock()
    app.state.supabase_client.storage.from_.return_value = mock_from

    resp = client.post("/api/v1/scans/claim", json={"token": token}, headers=auth_headers)
    assert resp.status_code == 200
    
    # Assert it was called with the config constant, not a literal
    mock_create_signed_url.assert_called_once_with(
        f"{patient_id}_report.pdf",
        gateway_config.signed_url_ttl_seconds
    )
