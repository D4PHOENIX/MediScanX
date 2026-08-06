"""Report generation and secure download endpoints.

Orchestrates the retrieval of historical diagnostic metadata, synthesis of
LLM interpretations, generation of standardized PDF clinical reports, and
secure cloud storage integration via signed access URLs.
"""

from __future__ import annotations

from typing import Any, Dict, List

import asyncpg
from fastapi import APIRouter, HTTPException, Depends, Request, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.core.config import gateway_config
from app.core.security import get_current_user
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

    # Generate PDF and upload to Supabase
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

    # Insert the new report record; perform compensating delete if this fails.
    conn: asyncpg.Connection = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            """
            INSERT INTO reports (report_id, user_id, scan_ids, storage_path, generated_by)
            VALUES ($1::uuid, $2::uuid, $3::uuid[], $4, $5::uuid)
            """,
            report_id,
            payload.patient_id,
            payload.selected_scan_ids,
            file_name,
            current_user
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to insert report {report_id}: {e}. Running compensating delete.")
        try:
            await request.app.state.supabase_client.storage.from_("medical_reports").remove([file_name])
        except Exception as rm_exc:
            logging.getLogger(__name__).error(f"Compensating delete failed for {file_name}: {rm_exc}")
        raise HTTPException(status_code=500, detail="Failed to save report record") from e
    finally:
        await conn.close()

    return {
        "message": "Report generated",
        "patient_id": payload.patient_id,
        "signed_url": signed_url,
        "report_id": report_id,
    }


@router.get("/download/{patient_id}")
async def download_report(patient_id: str, request: Request, current_user: str = Depends(get_current_user)) -> RedirectResponse:
    """Redirects the client to the securely signed cloud storage URL for the report.

    Args:
        patient_id (str): The universal identifier of the target patient.
        request (Request): The incoming FastAPI request (provides access to app state).

    Returns:
        RedirectResponse: A 307 Temporary Redirect to the Supabase storage object.

    Raises:
        HTTPException: Raises 404 if the report has not been generated, or 500
            if cloud storage integration fails.
    """
    
    # 1. Enforce tenant ownership (or care access) before signing a URL
    dsn: str | None = gateway_config.database_url
    if not dsn:
        raise HTTPException(status_code=500, detail="DATABASE_URL not set")

    conn: asyncpg.Connection = await asyncpg.connect(dsn)
    try:
        if current_user != patient_id:
            # Check care relationship if caller is not the patient
            has_access = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM care_relationships 
                    WHERE doctor_id = $1::uuid 
                      AND patient_id = $2::uuid 
                      AND status = 'active'
                      AND (expires_at IS NULL OR expires_at > now())
                )
                """,
                current_user,
                patient_id
            )
            if not has_access:
                raise HTTPException(status_code=403, detail="Access denied")
    finally:
        await conn.close()
        
    # Using a deterministic path allows any worker to resolve the file location.
    file_path = f"{patient_id}_report.pdf"

    sb_client = request.app.state.supabase_client
    try:
        bucket = sb_client.storage.from_("medical_reports")
        signed_url = await ReportGenerator.sign_report_url(bucket, file_path, raise_on_failure=True)
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
    """List reports the caller has access to view."""
    dsn: str | None = gateway_config.database_url
    if not dsn:
        raise HTTPException(status_code=500, detail="DATABASE_URL not set")

    conn: asyncpg.Connection = await asyncpg.connect(dsn)
    try:
        count_query = """
            SELECT COUNT(*) FROM reports
            WHERE (user_id = $1::uuid OR EXISTS (
                SELECT 1 FROM care_relationships 
                WHERE doctor_id = $1::uuid 
                  AND patient_id = reports.user_id 
                  AND status = 'active'
                  AND (expires_at IS NULL OR expires_at > now())
            ))
        """
        total_count = await conn.fetchval(count_query, current_user)

        data_query = """
            SELECT report_id, user_id, created_at, array_length(scan_ids, 1) as scan_count, storage_path
            FROM reports
            WHERE (user_id = $1::uuid OR EXISTS (
                SELECT 1 FROM care_relationships 
                WHERE doctor_id = $1::uuid 
                  AND patient_id = reports.user_id 
                  AND status = 'active'
                  AND (expires_at IS NULL OR expires_at > now())
            ))
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
        """
        rows = await conn.fetch(data_query, current_user, limit, offset)
    finally:
        await conn.close()

    items = []
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

        items.append(ReportItem(
            report_id=report_id,
            created_at=row["created_at"],
            scan_count=row["scan_count"],
            url=signed_url,
            patient_ref=patient_ref
        ))

    return ReportListResponse(total_count=total_count, items=items)


@router.delete("/{report_id}", status_code=204)
async def delete_report(
    report_id: str,
    request: Request,
    current_user: str = Depends(get_current_user)
):
    """Delete a report. Only the patient who owns the report can delete it."""
    dsn: str | None = gateway_config.database_url
    if not dsn:
        raise HTTPException(status_code=500, detail="DATABASE_URL not set")

    conn: asyncpg.Connection = await asyncpg.connect(dsn)
    try:
        # 1. Ownership checked in the query
        row = await conn.fetchrow(
            "SELECT storage_path FROM reports WHERE report_id = $1::uuid AND user_id = $2::uuid",
            report_id, current_user
        )
        if not row:
            raise HTTPException(status_code=404, detail="Report not found")

        storage_path = row["storage_path"]
        
        # Delete from storage first
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

        # Delete from DB only if storage deletion succeeds
        await conn.execute("DELETE FROM reports WHERE report_id = $1::uuid", report_id)
    finally:
        await conn.close()
