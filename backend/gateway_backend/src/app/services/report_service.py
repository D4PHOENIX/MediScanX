"""Report generation service for clinical PDF summaries with QR codes.

Orchestration only: database reads, image retrieval from storage, the LLM
call, PDF upload, and signed-URL creation. Layout lives in
``report_layout``, value formatting in ``report_format``, and visual
constants in ``report_theme``.

``_get_status`` and ``generate_hedged_text`` are re-exported here because
existing tests import and patch them at this path.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import qrcode

from app.core.config import gateway_config
from app.services.llm_service import generate_hedged_text
from app.services.report_format import _get_status, build_impression_prompt
from app.services.report_layout import build_pdf_story

logger = logging.getLogger(__name__)

__all__ = ["ReportGenerator", "_get_status", "generate_hedged_text"]


class ReportGenerator:
    """Service orchestrating the generation of comprehensive clinical PDF reports.

    This service synthesizes diagnostic findings, machine learning classification
    metadata, and LLM-generated clinical summaries into a standardized PDF format.
    It additionally manages secure cloud storage and the generation of embedded
    QR codes for seamless report access.
    """

    @staticmethod
    async def sign_report_url(bucket, storage_path: str, raise_on_failure: bool = False) -> str | None:
        """Create a signed URL for a report in storage.

        Args:
            bucket: The Supabase storage bucket instance
            storage_path: The path to the object
            raise_on_failure: If true, raises RuntimeError on failure; else returns None and logs.
        """
        try:
            signed_resp = await bucket.create_signed_url(storage_path, 60 * 60 * 24)  # 24 hours
            signed_url = signed_resp.get("signedURL") or signed_resp.get("signedUrl")
            if not signed_url:
                raise RuntimeError("Could not extract signed URL from Supabase response")
            return signed_url
        except Exception as e:
            logger.warning(f"Failed to sign URL for report at {storage_path}: {e}")
            if raise_on_failure:
                raise RuntimeError(f"Could not create signed URL: {e}") from e
            return None

    @staticmethod
    async def fetch_scan_metadata(dsn: str, selected_scan_ids: List[str], current_user: str) -> List[Dict[str, Any]]:
        """Retrieve diagnostic scan metadata securely scoped to a patient or authorized doctor.

        Fetches the modality, predicted diagnoses, confidences, and explainability
        paths for a specific set of scan IDs. Enforces access control by ensuring
        the requesting user either owns the scans (patient) or has an active care
        relationship with the patient (doctor).

        Args:
            dsn (str): Database connection string.
            selected_scan_ids (List[str]): UUIDs of the specific scans to include in the report.
            current_user (str): UUID of the authenticated user requesting the metadata.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries containing the authorized scan metadata.
        """
        import asyncpg
        conn: asyncpg.Connection = await asyncpg.connect(dsn)
        try:
            rows: List[asyncpg.Record] = await conn.fetch(
                """
                SELECT scan_id, modality, ai_diagnosis, confidence, scan_date,
                       xai_status, xai_path, storage_path
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
                selected_scan_ids,
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
                    "storage_path": row["storage_path"],
                }
            )
        return scan_metadata

    @staticmethod
    async def fetch_patient_header(patient_id: str) -> Optional[Dict[str, Any]]:
        """Fetch the demographics shown in the report header.

        Deliberately limited to name, username, date of birth and sex. Email,
        phone, location and medical history are never rendered — this document
        is designed to be shared, and additional PII on it is not an
        improvement.

        Reads the DSN from config rather than accepting one, so no caller
        signature changes and the router is untouched.

        Fails soft: any error returns None and the report falls back to a
        record-number-only header. A demographics lookup must never prevent a
        clinically valid report from being produced.
        """
        dsn = gateway_config.database_url
        if not dsn:
            return None
        try:
            import asyncpg
            conn = await asyncpg.connect(dsn)
            try:
                row = await conn.fetchrow(
                    """
                    SELECT full_name, username, date_of_birth, gender
                    FROM patient_records
                    WHERE user_id = $1::uuid
                    """,
                    patient_id,
                )
            finally:
                await conn.close()
            if not row:
                return None
            return {
                "full_name": row["full_name"],
                "username": row["username"],
                "date_of_birth": row["date_of_birth"],
                "gender": row["gender"],
            }
        except Exception as exc:
            logger.warning(f"Could not fetch patient header for {patient_id}: {exc}")
            return None

    def _build_pdf_story(
        self,
        patient_id: str,
        scan_metadata: List[Dict[str, Any]],
        xai_images: Dict[str, bytes],
        original_images: Dict[str, bytes],
        ai_summary: Optional[str] = None,
        qr_img: Optional[Any] = None,
        report_id: Optional[str] = None,
        patient_info: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        """Constructs the PDF document layout and renders it to a byte stream."""
        return build_pdf_story(
            patient_id,
            scan_metadata,
            xai_images,
            original_images,
            ai_summary=ai_summary,
            qr_img=qr_img,
            report_id=report_id,
            patient_info=patient_info,
        )

    async def generate_qr_report(
        self,
        patient_id: str,
        scan_metadata: List[Dict[str, Any]],
        supabase_client: Any = None,
    ) -> Tuple[bytes, str, str, str]:
        """Generates a complete clinical PDF report with cloud storage integration.

        This orchestration method produces a preliminary PDF, secures a cloud storage
        location, generates a signed access URL, embeds this URL as a QR code within
        the final PDF, and finalizes the cloud storage upload.

        Args:
            patient_id (str): The unique identifier assigned to the patient.
            scan_metadata (List[Dict[str, Any]]): A collection of dictionaries detailing
                the specific diagnostic scans to be included in the report.
            supabase_client: The shared Supabase client (async or sync) from ``app.state``.

        Returns:
            Tuple[bytes, str, str, str]: A tuple containing:
                - The raw bytes of the final generated PDF report.
                - The secure, signed URL providing temporary access to the report.
                - The storage path identifier within the cloud bucket.
                - The unique identifier for the generated report.

        Raises:
            RuntimeError: If the cloud storage provider fails to generate a signed access URL.
        """
        if supabase_client is None:
            raise RuntimeError("supabase_client must be provided")
        bucket = supabase_client.storage.from_("medical_reports")

        # 0. Fetch Original and XAI images
        xai_images: Dict[str, bytes] = {}
        original_images: Dict[str, bytes] = {}
        img_bucket = gateway_config.supabase_storage_bucket

        for m in scan_metadata:
            scan_id = m.get("id")

            # Fetch original image
            storage_path = m.get("storage_path")
            if storage_path:
                try:
                    img_data = await supabase_client.storage.from_(img_bucket).download(storage_path)
                    original_images[scan_id] = img_data
                except Exception as e:
                    logger.warning(f"Failed to fetch original image at {storage_path}: {e}")

            # Fetch XAI heatmap
            if m.get("xai_status") == "generated" and m.get("xai_path"):
                try:
                    xai_data = await supabase_client.storage.from_(img_bucket).download(m.get("xai_path"))
                    xai_images[scan_id] = xai_data
                except Exception as e:
                    logger.warning(f"Failed to fetch XAI heatmap at {m.get('xai_path')}: {e}")

        # 0.25 Fetch patient demographics for the header. Fails soft — the
        # report is still valid with a record-number-only header.
        patient_info = await ReportGenerator.fetch_patient_header(patient_id)

        # 0.5 Generate AI Summary
        ai_summary = None
        if scan_metadata:
            ai_summary = await generate_hedged_text(build_impression_prompt(scan_metadata))

        # 1. Generate unique report ID and determine storage path
        import uuid
        report_id = uuid.uuid4()
        storage_path = f"{patient_id}/{report_id}.pdf"

        # 2. Build the JWT token and the final QR image encoding the claim URL
        from jose import jwt
        from datetime import datetime, timedelta

        token_payload = {
            "sub": patient_id,
            "scan_ids": [m.get("id") for m in scan_metadata],
            "exp": datetime.utcnow() + timedelta(hours=1),
            "purpose": "report_claim"
        }
        token = jwt.encode(token_payload, gateway_config.report_token_secret, algorithm="HS256")
        claim_url = f"{gateway_config.claim_base_url}?token={token}"

        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(claim_url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")

        # 3. Build the final PDF that includes the QR image
        final_pdf = self._build_pdf_story(
            patient_id,
            scan_metadata,
            xai_images,
            original_images,
            ai_summary=ai_summary,
            qr_img=qr_img,
            report_id=str(report_id),
            patient_info=patient_info,
        )

        # 4. Upload the final PDF as a distinct object
        await bucket.upload(
            path=storage_path,
            file=final_pdf,
            file_options={
                "content-type": "application/pdf",
            },
        )

        # 5. Obtain a signed URL pointing to the uploaded object
        signed_url = await ReportGenerator.sign_report_url(bucket, storage_path, raise_on_failure=True)

        return final_pdf, signed_url, storage_path, str(report_id)
