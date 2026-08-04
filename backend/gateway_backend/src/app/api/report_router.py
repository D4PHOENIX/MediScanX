"""Report generation and secure download endpoints.

Orchestrates the retrieval of historical diagnostic metadata, synthesis of
LLM interpretations, generation of standardized PDF clinical reports, and
secure cloud storage integration via signed access URLs.
"""

from __future__ import annotations

from typing import Any, Dict, List

import asyncpg
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.core.config import gateway_config
from app.core.security import get_current_user
from app.models.schemas import GenerateReportRequest
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

    conn: asyncpg.Connection = await asyncpg.connect(dsn)
    try:
        rows: List[asyncpg.Record] = await conn.fetch(
            """
            SELECT scan_id, modality, ai_diagnosis, confidence, scan_date,
                   xai_status, xai_path
            FROM scan_results
            WHERE scan_id = ANY($1::uuid[])
              AND (user_id = $2::uuid OR EXISTS (
                  SELECT 1 FROM care_relationships 
                  WHERE doctor_id = $2::uuid 
                    AND patient_id = scan_results.user_id 
                    AND status = 'active'
                    AND (expires_at IS NULL OR expires_at > now())
              ))
            """,
            payload.selected_scan_ids,
            current_user
        )
    finally:
        await conn.close()

    scan_metadata: List[Dict[str, Any]] = []
    for row in rows:
        scan_metadata.append(
            {
                "id": str(row["scan_id"]),
                "modality": row["modality"],
                "ai_diagnosis": row["ai_diagnosis"],
                "confidence": float(row["confidence"]) if row["confidence"] is not None else None,
                "timestamp": row["scan_date"].isoformat() if row["scan_date"] else "N/A",
                "xai_status": row["xai_status"],
                "xai_path": row["xai_path"],
            }
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
    pdf_bytes, signed_url, file_name = await gen.generate_qr_report(
        patient_id=payload.patient_id,
        scan_metadata=scan_metadata,
        supabase_client=request.app.state.supabase_client,
    )

    # The storage path is fully deterministic, eliminating the need for in-memory mapping.

    return {
        "message": "Report generated",
        "patient_id": payload.patient_id,
        "signed_url": signed_url,
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
        signed: Dict[str, Any] = await sb_client.storage.from_("medical_reports").create_signed_url(
            file_path, 60 * 60 * 24
        )
        # The response dictionary contains a key named ``signedURL``.
        signed_url: str | None = signed.get("signedURL") or signed.get("signedUrl")
        if not signed_url:
            raise ValueError("Empty signed URL")
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Report not found. Please generate first.") from exc

    return RedirectResponse(url=signed_url)
