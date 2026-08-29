"""Tests for DELETE /api/v1/scans/{scan_id} (B41) and orphan-visibility in list_reports.

Test matrix
-----------
1. Owner deletes own scan → 200, delete_scan_objects called with scan-images bucket
   and both paths.
2. Second user deletes same scan_id → 404, row still exists (execute for DELETE not called).
3. Non-existent scan_id → 404.
4. Malformed scan_id → 422.
5. Storage removal raises → row SURVIVES, 5xx. The mock raises; assert execute (DELETE)
   was never called.  This is the most important test: a mocked storage client that never
   raises previously hid a broken delete path behind tests that always succeeded.
6. xai_path NULL → deletes cleanly, delete_scan_objects called with only storage_path.
7. Both paths NULL → 200, row deleted, delete_scan_objects called zero times.
8. Object already absent in storage (remove() succeeds silently) → 200, row deleted.
9. A report referencing a deleted scan still exists; GET /reports shows
   surviving_scan_count below scan_count.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt as jose_jwt

from app.main import app
from app.core.security import get_current_user
from app.core.config import gateway_config


# ---------------------------------------------------------------------------
# Auth helpers (mirrors conftest.py / test_reports_rls.py approach)
# ---------------------------------------------------------------------------

_PRIVATE_PEM = """\
-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQggosyvr8VSPb/UTdv
DcYJONWOmcI73Woero+DzsLUIemhRANCAAQkTVAev2FwsLvIPUB14BrxKIOfCMCI
Ma3A1Hwa5ZONwmP/zmVP7WRoRkUbCQKowh/6PXkwMXtdsWPxyTNt5rcc
-----END PRIVATE KEY-----
"""

OWNER_ID = "aa000000-0000-4000-a000-000000000001"
OTHER_ID = "bb000000-0000-4000-b000-000000000002"

SCAN_ID = str(uuid.uuid4())
STORAGE_PATH = f"{OWNER_ID}/{SCAN_ID}.jpg"
XAI_PATH = f"{OWNER_ID}/{SCAN_ID}/overlay_0.png"


def _jwt(user_id: str) -> str:
    claims = {
        "sub": user_id,
        "role": "authenticated",
        "aud": "authenticated",
        "iss": "https://ppwnixwhaxpsqvufdggy.supabase.co/auth/v1",
        "exp": int(time.time()) + 3600,
    }
    return jose_jwt.encode(claims, _PRIVATE_PEM, algorithm="ES256", headers={"kid": "test-kid"})


def _auth(user_id: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {_jwt(user_id)}"}


# ---------------------------------------------------------------------------
# DB mock helpers
# ---------------------------------------------------------------------------

class _AcquireCtx:
    """Async context manager that returns a pre-configured asyncpg connection mock."""

    def __init__(self, conn: AsyncMock) -> None:
        self._conn = conn

    async def __aenter__(self) -> AsyncMock:
        return self._conn

    async def __aexit__(self, *_: Any) -> None:
        pass


def _mock_pool(fetchrow_return=None, execute_return=None) -> tuple[MagicMock, AsyncMock]:
    """Return (pool, conn) where conn.fetchrow and conn.execute are configurable."""
    conn = AsyncMock()
    conn.fetchrow.return_value = fetchrow_return
    conn.execute.return_value = execute_return
    pool = MagicMock()
    pool.acquire.return_value = _AcquireCtx(conn)
    return pool, conn


def _scan_row(storage_path: Optional[str] = STORAGE_PATH, xai_path: Optional[str] = XAI_PATH) -> Dict[str, Any]:
    """Minimal asyncpg-style record dict for a scan_results row."""
    return {"storage_path": storage_path, "xai_path": xai_path}


# ---------------------------------------------------------------------------
# Test 1 — Owner deletes own scan
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_owner_deletes_own_scan_200_calls_storage_with_both_paths():
    """Owner deletes their scan → 200, delete_scan_objects called with bucket and both paths."""
    pool, conn = _mock_pool(fetchrow_return=_scan_row())
    app.state.db_pool = pool
    app.state.supabase_client = MagicMock()
    app.dependency_overrides[get_current_user] = lambda: OWNER_ID

    with patch("app.api.scans_router.StorageService.delete_scan_objects", new_callable=AsyncMock) as mock_delete:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete(f"/api/v1/scans/{SCAN_ID}", headers=_auth(OWNER_ID))

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["deleted"] == SCAN_ID

    # Assert on the call itself — bucket name, user_id, both paths in order.
    mock_delete.assert_awaited_once_with(
        supabase_client=app.state.supabase_client,
        bucket=gateway_config.supabase_storage_bucket,
        user_id=OWNER_ID,
        object_paths=[STORAGE_PATH, XAI_PATH],
    )

    # Row DELETE was issued after storage succeeded.
    conn.execute.assert_awaited_once()
    delete_sql = conn.execute.call_args.args[0]
    assert "DELETE FROM scan_results" in delete_sql


# ---------------------------------------------------------------------------
# Test 2 — Second user attempts same scan_id → 404, row untouched
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_second_user_gets_404_and_row_survives():
    """A different user cannot delete the owner's scan; 404, no row deletion."""
    # The ownership query for OTHER_ID returns None (scan_id belongs to OWNER_ID).
    pool, conn = _mock_pool(fetchrow_return=None)
    app.state.db_pool = pool
    app.state.supabase_client = MagicMock()
    app.dependency_overrides[get_current_user] = lambda: OTHER_ID

    with patch("app.api.scans_router.StorageService.delete_scan_objects", new_callable=AsyncMock) as mock_delete:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete(f"/api/v1/scans/{SCAN_ID}", headers=_auth(OTHER_ID))

    app.dependency_overrides.clear()

    assert resp.status_code == 404
    # Storage was never touched.
    mock_delete.assert_not_awaited()
    # The DELETE SQL was never issued — post-state: row still exists.
    conn.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 3 — Non-existent scan_id → 404
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nonexistent_scan_id_returns_404():
    """Querying a scan_id that does not exist at all returns 404."""
    nonexistent = str(uuid.uuid4())
    pool, conn = _mock_pool(fetchrow_return=None)
    app.state.db_pool = pool
    app.state.supabase_client = MagicMock()
    app.dependency_overrides[get_current_user] = lambda: OWNER_ID

    with patch("app.api.scans_router.StorageService.delete_scan_objects", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete(f"/api/v1/scans/{nonexistent}", headers=_auth(OWNER_ID))

    app.dependency_overrides.clear()

    assert resp.status_code == 404
    conn.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 4 — Malformed scan_id → 422
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_malformed_scan_id_returns_422():
    """A scan_id that is not a valid UUID is rejected at the parse_uuid guard."""
    pool, _ = _mock_pool()
    app.state.db_pool = pool
    app.state.supabase_client = MagicMock()
    app.dependency_overrides[get_current_user] = lambda: OWNER_ID

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/api/v1/scans/not-a-uuid", headers=_auth(OWNER_ID))

    app.dependency_overrides.clear()

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Test 5 — Storage removal raises → row SURVIVES, 5xx
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_storage_failure_leaves_row_intact_and_returns_5xx():
    """When delete_scan_objects raises, the row is NOT deleted and a 5xx is returned.

    This is the critical regression test: any implementation that calls storage
    deletion after the row deletion would let this test pass falsely even if the
    row was already gone. Here the mock raises, and we assert that conn.execute
    (the DELETE SQL) was never awaited.
    """
    pool, conn = _mock_pool(fetchrow_return=_scan_row())
    app.state.db_pool = pool
    app.state.supabase_client = MagicMock()
    app.dependency_overrides[get_current_user] = lambda: OWNER_ID

    with patch(
        "app.api.scans_router.StorageService.delete_scan_objects",
        new_callable=AsyncMock,
        side_effect=RuntimeError("bucket unreachable"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete(f"/api/v1/scans/{SCAN_ID}", headers=_auth(OWNER_ID))

    app.dependency_overrides.clear()

    # Request must fail with a server error.
    assert resp.status_code >= 500
    # Row DELETE was never issued — the scan still exists.
    conn.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 6 — xai_path NULL → only storage_path passed to helper
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_null_xai_path_calls_storage_with_only_storage_path():
    """When xai_path is NULL, delete_scan_objects receives only storage_path."""
    pool, conn = _mock_pool(fetchrow_return=_scan_row(xai_path=None))
    app.state.db_pool = pool
    app.state.supabase_client = MagicMock()
    app.dependency_overrides[get_current_user] = lambda: OWNER_ID

    with patch("app.api.scans_router.StorageService.delete_scan_objects", new_callable=AsyncMock) as mock_delete:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete(f"/api/v1/scans/{SCAN_ID}", headers=_auth(OWNER_ID))

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    mock_delete.assert_awaited_once()
    _, called_kwargs = mock_delete.call_args
    assert called_kwargs["object_paths"] == [STORAGE_PATH]
    # xai_path is absent from the list.
    assert XAI_PATH not in called_kwargs["object_paths"]
    conn.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 7 — Both paths NULL → 200, row deleted, storage never called
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_both_paths_null_deletes_row_without_calling_storage():
    """When both storage_path and xai_path are NULL, storage is not called once."""
    pool, conn = _mock_pool(fetchrow_return=_scan_row(storage_path=None, xai_path=None))
    app.state.db_pool = pool
    app.state.supabase_client = MagicMock()
    app.dependency_overrides[get_current_user] = lambda: OWNER_ID

    with patch("app.api.scans_router.StorageService.delete_scan_objects", new_callable=AsyncMock) as mock_delete:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete(f"/api/v1/scans/{SCAN_ID}", headers=_auth(OWNER_ID))

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    # Storage helper must not be called at all.
    mock_delete.assert_not_awaited()
    # The row DELETE must still have been issued.
    conn.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 8 — Object already absent in storage → 200, row deleted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_already_absent_objects_succeed_and_row_is_deleted():
    """When storage remove() succeeds silently for already-absent objects, deletion completes."""
    pool, conn = _mock_pool(fetchrow_return=_scan_row())
    app.state.db_pool = pool
    app.state.supabase_client = MagicMock()
    app.dependency_overrides[get_current_user] = lambda: OWNER_ID

    # Supabase remove() for missing objects returns [] without raising.
    # delete_scan_objects does not inspect the return value, so it succeeds.
    with patch(
        "app.api.scans_router.StorageService.delete_scan_objects",
        new_callable=AsyncMock,
        return_value=None,  # no exception → success
    ) as mock_delete:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete(f"/api/v1/scans/{SCAN_ID}", headers=_auth(OWNER_ID))

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    # Storage was attempted (we don't skip just because we think it might be absent).
    mock_delete.assert_awaited_once()
    # Row was deleted.
    conn.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 9 — Report referencing deleted scan: report survives, surviving_scan_count
#          in the list response is below scan_count
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_report_referencing_deleted_scan_survives_and_surfaces_discrepancy():
    """After a scan is deleted, its referencing report still exists.

    The GET /api/v1/reports response must include the report with
    surviving_scan_count strictly less than scan_count, making the
    discrepancy visible to the client without deleting or mutating the
    report row or its scan_ids array.

    The delete endpoint is NOT called in this test. We directly exercise the
    list_reports handler against mocked state that simulates the post-deletion
    scenario: the report row still has two UUIDs in scan_ids, but only one of
    them still exists in scan_results.
    """
    import json
    import datetime
    import httpx
    from supabase import create_async_client
    from supabase.lib.client_options import AsyncClientOptions
    from app.core.supabase_client import _extract_bearer

    DELETED_SCAN_ID = str(uuid.uuid4())
    SURVIVING_SCAN_ID = str(uuid.uuid4())
    REPORT_ID = str(uuid.uuid4())

    # The report row has both scan UUIDs; this is never mutated on scan deletion.
    report_row = {
        "report_id": REPORT_ID,
        "user_id": OWNER_ID,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scan_ids": [DELETED_SCAN_ID, SURVIVING_SCAN_ID],
        "storage_path": f"{OWNER_ID}/{REPORT_ID}.pdf",
    }

    # ---- PostgREST transport returning the one report row ----
    class _Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, req: httpx.Request) -> httpx.Response:
            if "/auth/v1" in req.url.path:
                return httpx.Response(200, content=json.dumps({
                    "access_token": "tok", "refresh_token": "r", "expires_in": 3600,
                    "user": {"id": "x"},
                }).encode(), headers={"Content-Type": "application/json"})
            if "/rest/v1/reports" in req.url.path:
                rows = [report_row]
                body = json.dumps(rows).encode()
                count = len(rows)
                high = max(count - 1, 0)
                return httpx.Response(200, content=body, headers={
                    "Content-Type": "application/json",
                    "Content-Range": f"0-{high}/{count}",
                })
            return httpx.Response(200, content=b"[]", headers={"Content-Type": "application/json"})

    async def _make_client(request):
        from app.core.config import gateway_config as _cfg
        token = _extract_bearer(request)
        opts = AsyncClientOptions(
            headers={"Authorization": f"Bearer {token}"},
            httpx_client=httpx.AsyncClient(transport=_Transport()),
        )
        return await create_async_client(_cfg.supabase_url, _cfg.supabase_publishable_key, options=opts)

    # ---- asyncpg mock: scan_results only has SURVIVING_SCAN_ID ----
    surviving_row = MagicMock()
    surviving_row.__getitem__ = lambda self, key: SURVIVING_SCAN_ID if key == "scan_id" else None

    class _SurvivingConn:
        async def fetch(self, *args, **kwargs):
            # Return only the surviving scan
            return [{"scan_id": SURVIVING_SCAN_ID}]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

    class _SurvivingPool:
        def acquire(self):
            return _SurvivingAcquire()

    class _SurvivingAcquire:
        async def __aenter__(self):
            return _SurvivingConn()

        async def __aexit__(self, *_):
            pass

    # ---- Service-role mock for storage URL signing ----
    mock_sb = MagicMock()
    mock_bucket = AsyncMock()
    mock_bucket.create_signed_url.return_value = {"signedURL": "https://signed.example/r.pdf"}
    mock_sb.storage.from_.return_value = mock_bucket

    app.state.db_pool = _SurvivingPool()
    app.state.supabase_client = mock_sb
    app.dependency_overrides[get_current_user] = lambda: OWNER_ID

    with patch("app.api.report_router.make_user_client", side_effect=_make_client):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/reports", headers=_auth(OWNER_ID))

    app.dependency_overrides.clear()

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert len(data["items"]) == 1

    item = data["items"][0]
    assert item["report_id"] == REPORT_ID

    # scan_count reflects what was recorded at generation time (2 scans).
    assert item["scan_count"] == 2, (
        f"scan_count should be 2 (recorded at generation), got {item['scan_count']}"
    )

    # surviving_scan_count reflects what still exists (1 scan survived deletion).
    assert item["surviving_scan_count"] == 1, (
        f"surviving_scan_count should be 1 (one scan deleted), got {item['surviving_scan_count']}"
    )

    # The discrepancy is visible to the client.
    assert item["surviving_scan_count"] < item["scan_count"], (
        "surviving_scan_count must be less than scan_count to surface the discrepancy"
    )
