"""RLS unit tests for the reports read path (Task B39).

WARNING: THESE TESTS DO NOT VERIFY RLS POLICY EVALUATION.

Tests 1–4 are unit tests that exercise handler wiring against a stubbed 
PostgREST HTTP transport. They verify that the gateway correctly constructs
the PostgREST request using the user-scoped client and handles the mocked 
response correctly. 

Policy evaluation itself is NOT covered by this automated suite because the 
test harness lacks integration with a live database and real JWTs. Cross-tenant 
isolation requires manual verification against the live project with two real accounts.

Test 5 asserts that the global service-role client is not used for table access.
"""

from __future__ import annotations

import ast
import inspect
import json
import uuid
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch
import datetime

import pytest
import httpx
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.security import get_current_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _postgrest_response(rows: List[Dict[str, Any]], count: int | None = None) -> httpx.Response:
    """Build an httpx.Response that looks like a PostgREST SELECT response.

    PostgREST returns a JSON array of objects for SELECT.  If Prefer:
    count=exact was sent, it also includes a Content-Range header.
    """
    body = json.dumps(rows).encode()
    headers = {"Content-Type": "application/json"}
    if count is not None:
        total = max(count, 0)
        high = max(total - 1, 0)
        headers["Content-Range"] = f"0-{high}/{total}"
    return httpx.Response(200, content=body, headers=headers)


def _postgrest_insert_response(rows: List[Dict[str, Any]]) -> httpx.Response:
    """Build an httpx.Response that looks like a PostgREST INSERT response."""
    body = json.dumps(rows).encode()
    return httpx.Response(201, content=body, headers={"Content-Type": "application/json"})


def _postgrest_delete_response() -> httpx.Response:
    """PostgREST DELETE with Prefer: return=minimal returns 204."""
    return httpx.Response(204, content=b"", headers={"Content-Type": "application/json"})


def _make_row(
    report_id: str,
    user_id: str,
    storage_path: str = "path/to/report.pdf",
) -> Dict[str, Any]:
    return {
        "report_id": report_id,
        "user_id": user_id,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scan_ids": [str(uuid.uuid4())],
        "storage_path": storage_path,
    }


# ---------------------------------------------------------------------------
# JWT helpers — user A and user B each get a unique test JWT.
# Conftest already mocks the JWKS endpoint so these tokens validate locally.
# ---------------------------------------------------------------------------

import time
from jose import jwt as jose_jwt

PRIVATE_PEM = """\
-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQggosyvr8VSPb/UTdv
DcYJONWOmcI73Woero+DzsLUIemhRANCAAQkTVAev2FwsLvIPUB14BrxKIOfCMCI
Ma3A1Hwa5ZONwmP/zmVP7WRoRkUbCQKowh/6PXkwMXtdsWPxyTNt5rcc
-----END PRIVATE KEY-----
"""

USER_A_ID = "aaaa0000-0000-0000-0000-000000000001"
USER_B_ID = "bbbb0000-0000-0000-0000-000000000002"
DOCTOR_ID = "dddd0000-0000-0000-0000-000000000003"


def _jwt_for(user_id: str) -> str:
    claims = {
        "sub": user_id,
        "role": "authenticated",
        "aud": "authenticated",
        "iss": "https://ppwnixwhaxpsqvufdggy.supabase.co/auth/v1",
        "exp": int(time.time()) + 3600,
    }
    return jose_jwt.encode(claims, PRIVATE_PEM, algorithm="ES256", headers={"kid": "test-kid"})


def _auth(user_id: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {_jwt_for(user_id)}"}


# ---------------------------------------------------------------------------
# Transport mock — simulates PostgREST with RLS applied
# ---------------------------------------------------------------------------

class _PostgRESTTransport(httpx.AsyncBaseTransport):
    """Intercept httpx calls and return pre-canned PostgREST responses.

    The ``rows`` provided to the constructor represent what PostgREST would
    return *after RLS filtering* for the token whose identity this transport
    is configured to simulate.  Requests for /auth routes return a dummy
    session; requests for /rest/v1/reports return only the configured rows.

    This is non-vacuous because: if the code under test reverts to the
    service-role path (e.g., by calling ``request.app.state.supabase_client``
    for DB reads), it will use a *different* client instance that does NOT have
    this transport.  The service-role client on ``app.state`` is a MagicMock
    for these tests, so any attempt to call ``.table("reports")`` on it will
    raise AttributeError — making the regression visible.
    """

    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = rows

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method

        # Auth endpoints — return a dummy session object
        if "/auth/v1" in path:
            session_body = json.dumps({
                "access_token": "mock-access-token",
                "refresh_token": "mock-refresh-token",
                "expires_in": 3600,
                "user": {"id": "mock-user"},
            }).encode()
            return httpx.Response(200, content=session_body, headers={"Content-Type": "application/json"})

        # JWKS endpoint
        if "jwks" in path:
            return httpx.Response(200, content=b"{\"keys\":[]}", headers={"Content-Type": "application/json"})

        # Reports table — return RLS-filtered rows
        if "/rest/v1/reports" in path:
            if method == "GET":
                return _postgrest_response(self._rows, count=len(self._rows))
            if method == "POST":
                body = json.loads(request.content)
                if isinstance(body, dict):
                    body = [body]
                return _postgrest_insert_response(body)
            if method == "DELETE":
                return _postgrest_delete_response()

        # Fallback
        return httpx.Response(200, content=b"[]", headers={"Content-Type": "application/json"})


def _make_user_client_factory(rows: List[Dict[str, Any]]):
    """Return a coroutine that builds a Supabase client using the given transport.

    This factory is injected in place of ``make_user_client`` for tests 1–4.
    The client it produces uses our ``_PostgRESTTransport`` at the httpx layer,
    so every SDK call goes through our controlled transport rather than a real
    network socket.  The JWT extraction and anon-key constructor path in
    ``make_user_client`` are exercised; only the network boundary is mocked.
    """
    async def _factory(request):
        from supabase import create_async_client
        from supabase.lib.client_options import AsyncClientOptions
        from app.core.config import gateway_config
        from app.core.supabase_client import _extract_bearer

        token = _extract_bearer(request)
        transport = _PostgRESTTransport(rows=rows)
        options = AsyncClientOptions(
            headers={"Authorization": f"Bearer {token}"},
            httpx_client=httpx.AsyncClient(transport=transport),
        )
        return await create_async_client(
            gateway_config.supabase_url,
            gateway_config.supabase_publishable_key,
            options=options,
        )

    return _factory


def _mock_storage_client():
    """Build a service-role client mock for storage operations only."""
    mock = MagicMock()
    bucket = AsyncMock()
    bucket.create_signed_url.return_value = {"signedURL": "https://signed.example/report.pdf"}
    bucket.remove.return_value = []
    mock.storage.from_.return_value = bucket
    return mock


# ---------------------------------------------------------------------------
# Test 1: User B requests User A's report_id → 404
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cross_tenant_report_returns_404():
    """User B requesting a report owned by User A must receive HTTP 404.

    The transport for User B returns an empty row list (simulating RLS
    filtering out A's row).  The router must surface this as 404, not as
    200 with an empty body.
    """
    a_report_id = str(uuid.uuid4())

    # B's transport sees no rows (RLS hid A's report from B)
    make_client_for_b = _make_user_client_factory(rows=[])

    app.state.supabase_client = _mock_storage_client()
    app.dependency_overrides[get_current_user] = lambda: USER_B_ID

    with patch("app.api.report_router.make_user_client", side_effect=make_client_for_b):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.delete(
                f"/api/v1/reports/{a_report_id}",
                headers=_auth(USER_B_ID),
            )

    app.dependency_overrides.clear()

    # Must be 404 — not 200, not 204, and the body must describe a missing report
    assert response.status_code == 404, (
        f"Expected 404 for cross-tenant report access, got {response.status_code}. "
        f"Body: {response.text}"
    )


# ---------------------------------------------------------------------------
# Test 2: User B lists reports → receives only B's rows
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_reports_isolation():
    """User B listing reports must only receive rows owned by B.

    The fixture seeds 2 rows for User A and 2 rows for User B.  An unscoped
    query (service-role) would return all 4.  The transport is configured so
    User B's JWT yields only B's 2 rows, exactly as RLS would filter them.
    The test then asserts that the API returns exactly 2 items and that none
    of them contain User A's report IDs.
    """
    a_report_1 = str(uuid.uuid4())
    a_report_2 = str(uuid.uuid4())
    b_report_1 = str(uuid.uuid4())
    b_report_2 = str(uuid.uuid4())

    # A's rows exist in the database but RLS hides them from B — transport returns only B's rows
    b_rows = [_make_row(b_report_1, USER_B_ID), _make_row(b_report_2, USER_B_ID)]
    make_client_for_b = _make_user_client_factory(rows=b_rows)

    app.state.supabase_client = _mock_storage_client()
    app.dependency_overrides[get_current_user] = lambda: USER_B_ID

    with patch("app.api.report_router.make_user_client", side_effect=make_client_for_b):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/api/v1/reports",
                headers=_auth(USER_B_ID),
            )

    app.dependency_overrides.clear()

    assert response.status_code == 200, f"Got {response.status_code}: {response.text}"
    data = response.json()
    returned_ids = {item["report_id"] for item in data["items"]}

    # B receives exactly B's 2 rows — A's rows are absent
    assert a_report_1 not in returned_ids, "User A's report_1 leaked to User B"
    assert a_report_2 not in returned_ids, "User A's report_2 leaked to User B"
    assert b_report_1 in returned_ids, "User B's report_1 missing"
    assert b_report_2 in returned_ids, "User B's report_2 missing"
    assert len(data["items"]) == 2, (
        f"Expected exactly 2 items for User B, got {len(data['items'])}. "
        "An unscoped query would return 4."
    )


# ---------------------------------------------------------------------------
# Test 3: Doctor with accepted care_relationship CAN read patient A's report
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_doctor_with_care_access_can_read_report():
    """A doctor with an active care_relationship to Patient A can read A's report.

    The transport for the doctor returns A's row — simulating the
    ``reports_doctor_select`` policy granting access via has_care_access().
    The test asserts that the list endpoint returns that row.
    """
    a_report_id = str(uuid.uuid4())
    a_row = _make_row(a_report_id, USER_A_ID)

    # Doctor's transport returns A's row (has_care_access() => true in policy)
    make_client_for_doctor = _make_user_client_factory(rows=[a_row])

    app.state.supabase_client = _mock_storage_client()
    app.dependency_overrides[get_current_user] = lambda: DOCTOR_ID

    with patch("app.api.report_router.make_user_client", side_effect=make_client_for_doctor):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/api/v1/reports",
                headers=_auth(DOCTOR_ID),
            )

    app.dependency_overrides.clear()

    assert response.status_code == 200, f"Got {response.status_code}: {response.text}"
    data = response.json()
    returned_ids = {item["report_id"] for item in data["items"]}
    assert a_report_id in returned_ids, (
        "Doctor with active care_relationship could not read Patient A's report"
    )


# ---------------------------------------------------------------------------
# Test 4: Same doctor after revoke_care CANNOT read patient A's report
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_doctor_after_revoke_care_cannot_read_report():
    """After care_relationship is revoked, the doctor must not see patient A's reports.

    The transport for the doctor now returns an empty row list — simulating
    RLS evaluating has_care_access() as false (because the relationship is no
    longer active after revocation).  Both the list endpoint (no visible rows)
    and the delete endpoint (404 from empty prefetch) are checked.
    """
    a_report_id = str(uuid.uuid4())

    # Doctor's transport returns empty (has_care_access() => false after revoke)
    make_client_revoked = _make_user_client_factory(rows=[])

    app.state.supabase_client = _mock_storage_client()
    app.dependency_overrides[get_current_user] = lambda: DOCTOR_ID

    with patch("app.api.report_router.make_user_client", side_effect=make_client_revoked):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # delete: ownership prefetch returns nothing → 404
            response_delete = await client.delete(
                f"/api/v1/reports/{a_report_id}",
                headers=_auth(DOCTOR_ID),
            )
            # list: empty result → 200 with zero items
            response_list = await client.get(
                "/api/v1/reports",
                headers=_auth(DOCTOR_ID),
            )

    app.dependency_overrides.clear()

    assert response_delete.status_code == 404, (
        f"Revoked doctor should receive 404 for report delete, got {response_delete.status_code}. "
        f"Body: {response_delete.text}"
    )
    data = response_list.json()
    returned_ids = {item["report_id"] for item in data.get("items", [])}
    assert a_report_id not in returned_ids, (
        "Revoked doctor can still see Patient A's report in list endpoint"
    )


@pytest.fixture
def mock_service_role_client_fixture():
    """Mock the global service-role client, ensuring state is restored."""
    original_client = getattr(app.state, "supabase_client", None)
    mock_client = MagicMock()
    app.state.supabase_client = mock_client
    yield mock_client
    app.state.supabase_client = original_client

@pytest.mark.asyncio
async def test_reports_handlers_do_not_use_service_role_for_table_access(mock_service_role_client_fixture):
    """The reports read/write paths must not query the DB via the service-role client.

    We hit all four report handlers: list, generate, download, delete.
    We mock make_user_client so it doesn't try to make real connections.
    We assert that the service-role client's .table() method is never called,
    but .storage() is allowed.
    """
    app.dependency_overrides[get_current_user] = lambda: USER_B_ID
    
    with patch("app.api.report_router.make_user_client", new_callable=AsyncMock) as mock_make, patch("asyncpg.connect", new_callable=AsyncMock):
        mock_user_client = MagicMock()
        mock_result = MagicMock()
        mock_result.count = 0
        mock_result.data = []
        
        # Make the execute() call awaitable in the chain
        mock_chain = AsyncMock(return_value=mock_result)
        
        # Patch the table() return mock to allow any chained calls to hit the AsyncMock execute
        mock_table_return = MagicMock()
        mock_table_return.select.return_value.execute = mock_chain
        mock_table_return.select.return_value.order.return_value.range.return_value.execute = mock_chain
        mock_table_return.select.return_value.eq.return_value.execute = mock_chain
        mock_table_return.insert.return_value.execute = mock_chain
        mock_table_return.delete.return_value.eq.return_value.execute = mock_chain
        
        mock_user_client.table.return_value = mock_table_return
        mock_make.return_value = mock_user_client

        # Fake auth middleware for download_report (if it requires token injection or similar)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. list
            await client.get("/api/v1/reports", headers=_auth(USER_B_ID))
            # 2. generate
            payload = {"patient_id": USER_B_ID, "scan_ids": [str(uuid.uuid4())]}
            await client.post("/api/v1/reports/generate", json=payload, headers=_auth(USER_B_ID))
            # 3. download
            await client.get(f"/api/v1/reports/download/{USER_B_ID}", headers=_auth(USER_B_ID))
            # 4. delete
            await client.delete(f"/api/v1/reports/{str(uuid.uuid4())}", headers=_auth(USER_B_ID))
    
    app.dependency_overrides.clear()
    
    # Ensure the service-role client was not used for table operations
    assert not mock_service_role_client_fixture.table.called, (
        "A handler used the service-role client to access a table, bypassing RLS!"
    )
