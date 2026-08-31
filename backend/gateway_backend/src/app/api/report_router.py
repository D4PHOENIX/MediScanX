"""Report generation and secure download endpoints.

Orchestrates the retrieval of historical diagnostic metadata, synthesis of
LLM interpretations, generation of standardized PDF clinical reports, and
secure cloud storage integration via signed access URLs.

Access control model
--------------------
All reads and writes against ``public.reports`` use a **request-scoped**
Supabase client constructed with the anon key and the caller's bearer token
(see ``app.core.supabase_client.make_user_client``).  This causes PostgREST to
evaluate the two existing SELECT policies and the owner-scoped INSERT / DELETE
policies added in migration 0002.  The service-role client (``app.state.supabase_client``)
is used exclusively for Supabase Storage operations; it never touches the
``reports`` table.
"""

from __future__ import annotations

from typing import Any, Dict, List


from fastapi import APIRouter, HTTPException, Depends, Request, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.core.config import gateway_config
from app.core.security import get_current_user
from app.core.supabase_client import make_user_client
from app.models.schemas import GenerateReportRequest, ReportListResponse, ReportItem
from app.services.report_service import ReportGenerator

router: APIRouter = APIRouter(prefix="/reports", tags=["reports"], dependencies=[Depends(get_current_user)])


@router.post("/generate")
async def generate_report(payload: GenerateReportRequest, request: Request, current_user: str = Depends(get_current_user)) -> Dict[str, str]:
    """Creates a comprehensive clinical PDF report and stages it in cloud storage.

    Aggregates diagnostic metadata directly from the primary database, generates
    a formatted PDF document integrating the provided LLM summary, and secures
    temporary access via a signed cloud storage URL.

    Args:
        payload (GenerateReportRequest): The validated request payload.

    Returns:
        Dict[str, str]: A confirmation payload containing the signed access URL.

    Raises:
        HTTPException: Raises 500 if the database connection fails or configuration is missing.
    """

    # Fetch scan metadata from the database
    dsn: str | None = gateway_config.database_url
    if not dsn:
        raise HTTPException(status_code=500, detail="DATABASE_URL not set")

    scan_metadata = await ReportGenerator.fetch_scan_metadata(
        dsn=dsn,
        selected_scan_ids=payload.selected_scan_ids,
        current_user=current_user
    )

    if not scan_metadata:
        raise HTTPException(status_code=403, detail="No matching scans found or access denied")
        
    if len(scan_metadata) != len(payload.selected_scan_ids):
        raise HTTPException(status_code=403, detail="Access denied to one or more requested scans")

    # Generate PDF and upload to Supabase.
    # Storage operations legitimately use the service-role client: the
    # medical_reports bucket has its own object-level policy and the gateway
    # must upload on behalf of the patient.
    gen: ReportGenerator = ReportGenerator()
    pdf_bytes: bytes
    signed_url: str
    file_name: str
    report_id: str
    pdf_bytes, signed_url, file_name, report_id = await gen.generate_qr_report(
        patient_id=payload.patient_id,
        scan_metadata=scan_metadata,
        supabase_client=request.app.state.supabase_client,
    )

    # Insert the new report record using a request-scoped client so the
    # owner-scoped INSERT policy (migration 0002) enforces the write.
    # Caller JWT is in scope — use the request-scoped client.
    user_client = await make_user_client(request)
    try:
        result = await user_client.table("reports").insert({
            "report_id": report_id,
            "user_id": payload.patient_id,
            "scan_ids": payload.selected_scan_ids,
            "storage_path": file_name,
            "generated_by": current_user,
        }).execute()
        if not result.data:
            raise RuntimeError("INSERT returned no data — RLS may have blocked the write")
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to insert report {report_id}: {e}. Running compensating delete.")
        try:
            await request.app.state.supabase_client.storage.from_("medical_reports").remove([file_name])
        except Exception as rm_exc:
            logging.getLogger(__name__).error(f"Compensating delete failed for {file_name}: {rm_exc}")
        raise HTTPException(status_code=500, detail="Failed to save report record") from e

    return {
        "message": "Report generated",
        "patient_id": payload.patient_id,
        "signed_url": signed_url,
        "report_id": report_id,
    }


@router.get("/download/{report_id}")
async def download_report(report_id: str, request: Request, current_user: str = Depends(get_current_user)) -> RedirectResponse:
    """Redirects the client to the securely signed cloud storage URL for the report.

    Uses the request-scoped Supabase client (caller JWT) so the existing RLS
    SELECT policies (``reports_patient_select`` and ``reports_doctor_select``)
    gate access.  No service-role read of ``reports`` occurs here — consistent
    with the list endpoint at :214.

    Args:
        report_id (str): The UUID of the target report.
        request (Request): The incoming FastAPI request (provides access to app state).

    Returns:
        RedirectResponse: A 307 Temporary Redirect to the Supabase storage object.

    Raises:
        HTTPException: Raises 404 if the report is not found or RLS denies access, or 500
            if cloud storage integration fails.
    """
    # Fetch storage_path through the request-scoped client so RLS scopes it.
    # An empty result means either the report doesn't exist or RLS denied access;
    # both surface as 404 to prevent enumeration.
    user_client = await make_user_client(request)
    fetch_result = await (
        user_client.table("reports")
        .select("storage_path")
        .eq("report_id", report_id)
        .execute()
    )
    rows = fetch_result.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Report not found. Please generate first.")

    storage_path: str = rows[0]["storage_path"]

    # Storage URL generation uses the service-role client: signed URL creation
    # is a storage control-plane operation, not a reports table read.
    sb_client = request.app.state.supabase_client
    try:
        bucket = sb_client.storage.from_("medical_reports")
        signed_url = await ReportGenerator.sign_report_url(bucket, storage_path, raise_on_failure=True)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Report not found. Please generate first.") from exc

    return RedirectResponse(url=signed_url)



@router.get("", response_model=ReportListResponse)
async def list_reports(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: str = Depends(get_current_user)
) -> ReportListResponse:
    """List reports the caller has access to view.

    Uses a request-scoped Supabase client so the two existing RLS SELECT
    policies (``reports_patient_select`` and ``reports_doctor_select``) do the
    row filtering.  The service-role client is never consulted for this query.
    A missing or empty result from RLS is surfaced as an empty list, not as an
    error, because zero owned reports is a valid state.

    Orphan visibility
    -----------------
    Each item carries ``surviving_scan_count``: the number of the report's
    recorded source scan UUIDs that still exist in ``scan_results``.  When
    ``surviving_scan_count < scan_count``, one or more source scans have been
    deleted.  The client should surface this discrepancy rather than silently
    rendering a gap.  The ``scan_ids`` array on the report row is never mutated.
    """
    # Caller JWT is in scope — use the request-scoped client.
    user_client = await make_user_client(request)

    # RLS policies filter rows automatically; no hand-authored WHERE needed.
    count_result = await (
        user_client.table("reports")
        .select("report_id", count="exact")
        .execute()
    )
    total_count: int = count_result.count or 0

    data_result = await (
        user_client.table("reports")
        .select("report_id, user_id, created_at, scan_ids, storage_path")
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    rows = data_result.data or []

    # --- Orphan visibility: find surviving source scans in one query ----------
    # Collect every scan UUID referenced by the current page of reports.
    # A single ANY($1) query then tells us which UUIDs still exist in
    # scan_results.  This avoids N+1 queries and does not require a new table.
    all_scan_uuids: list = []
    for row in rows:
        sids = row.get("scan_ids") or []
        all_scan_uuids.extend(sids)

    existing_scan_ids: set[str] = set()
    db_pool = request.app.state.db_pool
    if all_scan_uuids and db_pool:
        import logging as _log
        try:
            async with db_pool.acquire() as conn:
                surviving = await conn.fetch(
                    "SELECT DISTINCT scan_id FROM scan_results "
                    "WHERE scan_id = ANY($1::uuid[]) "
                    "AND ("
                    "  user_id = $2::uuid "
                    "  OR EXISTS ("
                    "    SELECT 1 FROM care_relationships cr "
                    "    WHERE cr.doctor_id = $2::uuid "
                    "      AND cr.patient_id = scan_results.user_id "
                    "      AND cr.status = 'active' "
                    "      AND (cr.expires_at IS NULL OR cr.expires_at > now())"
                    "  )"
                    ")",
                    all_scan_uuids,
                    current_user,
                )
            existing_scan_ids = {str(r["scan_id"]) for r in surviving}
        except Exception as exc:
            _log.getLogger(__name__).warning(
                "Could not compute surviving_scan_count for report list: %s", exc
            )
            # Non-fatal: surviving_scan_count will be None for all items.
    # -------------------------------------------------------------------------

    items = []
    # Storage URL signing uses the service-role client: this is a storage
    # control-plane operation against the medical_reports bucket, not a
    # reports table read.
    sb_client = request.app.state.supabase_client
    bucket = sb_client.storage.from_("medical_reports")

    for row in rows:
        report_id = str(row["report_id"])
        user_id = str(row["user_id"])

        patient_ref = None
        if user_id != current_user:
            patient_ref = f"PT-{user_id[:6].upper()}"

        storage_path = row["storage_path"]
        signed_url = await ReportGenerator.sign_report_url(bucket, storage_path, raise_on_failure=False)

        scan_ids = row.get("scan_ids")
        # Match PostgreSQL array_length semantics: returns None if the array is empty or null
        scan_count = len(scan_ids) if scan_ids else None

        surviving_scan_count = None
        if scan_ids and db_pool:
            surviving_scan_count = sum(
                1 for sid in scan_ids if str(sid) in existing_scan_ids
            )

        items.append(ReportItem(
            report_id=report_id,
            created_at=row["created_at"],
            scan_count=scan_count,
            url=signed_url,
            patient_ref=patient_ref,
            surviving_scan_count=surviving_scan_count,
        ))

    return ReportListResponse(total_count=total_count, items=items)



@router.delete("/{report_id}", status_code=204)
async def delete_report(
    report_id: str,
    request: Request,
    current_user: str = Depends(get_current_user)
):
    """Delete a report. Only the patient who owns the report can delete it.

    Uses a request-scoped Supabase client for both the ownership prefetch and
    the DELETE so the owner-scoped DELETE policy (migration 0002) enforces the
    operation.  RLS returning zero rows on the prefetch is surfaced as 404 —
    indistinguishable from a non-existent report_id to prevent enumeration.
    """
    # Caller JWT is in scope — use the request-scoped client.
    user_client = await make_user_client(request)

    # 1. Ownership prefetch — RLS policy limits visibility to the owner.
    #    An empty result means either (a) wrong owner or (b) no such report;
    #    both are 404 to prevent enumeration.
    fetch_result = await (
        user_client.table("reports")
        .select("storage_path")
        .eq("report_id", report_id)
        .execute()
    )
    rows = fetch_result.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Report not found")

    storage_path: str = rows[0]["storage_path"]
    
    # 2. Delete from storage first.
    # Storage delete uses the service-role client: the medical_reports bucket
    # has its own object-level policy and the gateway deletes on behalf of
    # the owner.
    sb_client = request.app.state.supabase_client
    bucket = sb_client.storage.from_("medical_reports")
    try:
        resp = await bucket.remove([storage_path])
        # supabase-py storage3 remove returns a list of deleted objects or an error dict
        if isinstance(resp, list):
            if len(resp) == 0:
                pass # Object already deleted or not found. Proceed to remove from DB.
            elif isinstance(resp[0], dict) and resp[0].get("error"):
                raise RuntimeError(str(resp[0]["error"]))
        elif isinstance(resp, dict) and resp.get("error"):
            raise RuntimeError(str(resp["error"]))
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to delete report object {storage_path}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete report object") from e

    # 3. Delete the row — request-scoped client; RLS DELETE policy enforces ownership.
    await (
        user_client.table("reports")
        .delete()
        .eq("report_id", report_id)
        .execute()
    )
