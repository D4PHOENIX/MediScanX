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

_report_paths: Dict[str, str] = {}




@router.post("/generate")
async def generate_report(payload: GenerateReportRequest, request: Request) -> Dict[str, str]:
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
            SELECT id, modality, predicted_class, created_at
            FROM patient_scans
            WHERE id = ANY($1::text[])
            """,
            payload.selected_scan_ids,
        )
    finally:
        await conn.close()

    scan_metadata: List[Dict[str, Any]] = []
    for row in rows:
        scan_metadata.append(
            {
                "id": row["id"],
                "modality": row["modality"],
                "class": row["predicted_class"],
                "timestamp": row["created_at"].isoformat() if row["created_at"] else "N/A",
            }
        )

    # Generate PDF and upload to Supabase
    gen: ReportGenerator = ReportGenerator()
    pdf_bytes: bytes
    signed_url: str
    file_name: str
    pdf_bytes, signed_url, file_name = await gen.generate_qr_report(
        patient_id=payload.patient_id,
        scan_metadata=scan_metadata,
        llm_summary=payload.llm_summary,
        supabase_client=request.app.state.supabase_client,
    )

    # Keep track of the storage path for the download endpoint.
    # Note: Using an in-memory dictionary is unsafe for multi-worker deployments.
    # Future enhancement should move this path resolution to Redis or Postgres.
    _report_paths[payload.patient_id] = file_name

    return {
        "message": "Report generated",
        "patient_id": payload.patient_id,
        "signed_url": signed_url,
    }


@router.get("/download/{patient_id}")
async def download_report(patient_id: str, request: Request) -> RedirectResponse:
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
    file_path: str | None = _report_paths.get(patient_id)
    if not file_path:
        raise HTTPException(status_code=404, detail="Report not found. Please generate first.")

    sb_client = request.app.state.supabase_client
    signed: Dict[str, Any] = await sb_client.storage.from_("medical_reports").create_signed_url(
        file_path, 60 * 60 * 24
    )
    # The response dictionary contains a key named ``signedURL``.
    signed_url: str | None = signed.get("signedURL") or signed.get("signedUrl")
    if not signed_url:
        raise HTTPException(status_code=500, detail="Could not generate signed URL")

    return RedirectResponse(url=signed_url)
