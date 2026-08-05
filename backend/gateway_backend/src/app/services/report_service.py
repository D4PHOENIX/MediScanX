"""Report generation service for clinical PDF summaries with QR codes.

This module orchestrates the synthesis of structured clinical PDF reports,
integrating diagnostic metadata, LLM-generated summaries, and securely
signed access URLs encoded as QR codes.
"""

from __future__ import annotations

import hashlib
import io
import os
from typing import Optional, Tuple, List, Dict, Any

import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
from app.utils.xai_utils import build_xai_authenticated_url
import httpx
from app.core.config import gateway_config
from app.services.llm_service import generate_hedged_text
from app.utils.labels import _ABNORMAL_LABELS, _NORMAL_LABELS

def _get_status(label: Optional[str], mod: Optional[str]) -> str:
    if not label or not mod:
        return "unknown"
    if label in _NORMAL_LABELS.get(mod, set()):
        return "normal"
    if label in _ABNORMAL_LABELS.get(mod, set()):
        return "abnormal"
    return "unknown"


class ReportGenerator:
    """Service orchestrating the generation of comprehensive clinical PDF reports.

    This service synthesizes diagnostic findings, machine learning classification
    metadata, and LLM-generated clinical summaries into a standardized PDF format.
    It additionally manages secure cloud storage and the generation of embedded
    QR codes for seamless report access.
    """

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
                }
            )
        return scan_metadata

    def _build_pdf_story(
        self,
        patient_id: str,
        scan_metadata: List[Dict[str, Any]],
        xai_images: Dict[str, bytes],
        ai_summary: Optional[str] = None,
        qr_img: Optional[Any] = None,
    ) -> bytes:
        """Constructs the PDF document layout and renders it to a byte stream.

        Assembles the clinical report using ReportLab platypus elements,
        structuring the document with standard margins, typographically distinct
        headings, organized metadata sections, and optional embedded imagery.

        Args:
            patient_id (str): The unique identifier assigned to the patient.
            scan_metadata (List[Dict[str, Any]]): A collection of dictionaries containing
                metadata for the relevant diagnostic scans (e.g., modality, class).
            xai_images (Dict[str, bytes]): Mapping of scan_id to XAI image bytes.
            ai_summary (Optional[str], optional): Generated clinical summary text. Defaults to None.
            qr_img (Optional[Any], optional): A PIL Image object representing the
                access QR code to be embedded in the report. Defaults to None.

        Returns:
            bytes: The fully rendered PDF document as a byte array.
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=72,
        )
        styles = getSampleStyleSheet()
        title_style = styles["Title"]
        body_style = styles["BodyText"]
        story = []

        story.append(Paragraph("MediScanX Clinical Report", title_style))
        story.append(Spacer(1, 0.2 * inch))
        story.append(Paragraph(f"Patient ID: {patient_id}", body_style))
        story.append(Spacer(1, 0.1 * inch))

        if ai_summary is not None:
            story.append(Paragraph("AI-Generated Clinical Summary", styles["Heading3"]))
            story.append(Spacer(1, 0.05 * inch))
            story.append(Paragraph(ai_summary, body_style))
            story.append(Spacer(1, 0.05 * inch))
            disclaimer_text = "This summary is AI-generated and may be incomplete or inaccurate. It is not a diagnosis. Discuss these results with a qualified clinician."
            disclaimer_style = styles["Italic"]
            story.append(Paragraph(disclaimer_text, disclaimer_style))
            story.append(Spacer(1, 0.1 * inch))

        # Scan metadata section
        story.append(Paragraph("Diagnostic Summary:", body_style))
        story.append(Spacer(1, 0.1 * inch))
        for m in scan_metadata:
            scan_id = m.get('id', '?')
            confidence = m.get('confidence')
            conf_str = f"{confidence:.2f}" if confidence is not None else "N/A"
            scan_text = (
                f"<b>Scan ID:</b> {scan_id}<br/>"
                f"<b>Modality:</b> {m.get('modality', 'N/A')}<br/>"
                f"<b>Diagnosis:</b> {m.get('ai_diagnosis', 'N/A')}<br/>"
                f"<b>Confidence:</b> {conf_str}<br/>"
                f"<b>Timestamp:</b> {m.get('timestamp', 'N/A')}"
            )
            story.append(Paragraph(scan_text, body_style))
            story.append(Spacer(1, 0.05 * inch))
            
            xai_status = m.get('xai_status')
            if xai_status == 'generated':
                img_bytes = xai_images.get(scan_id)
                if img_bytes:
                    img_buffer = io.BytesIO(img_bytes)
                    rl_image = RLImage(img_buffer, width=4 * inch, height=4 * inch)
                    story.append(rl_image)
                else:
                    story.append(Paragraph("<i>Heatmap available but failed to load.</i>", body_style))
            else:
                story.append(Paragraph(f"<i>No heatmap is available for this scan (status: {xai_status}).</i>", body_style))
                
            story.append(Spacer(1, 0.2 * inch))

        # QR code (if provided)
        if qr_img is not None:
            qr_buffer = io.BytesIO()
            # qr_img is a PIL Image; convert to PNG bytes in memory
            qr_img.save(qr_buffer, format="PNG")
            qr_buffer.seek(0)
            rl_image = RLImage(qr_buffer, width=2 * inch, height=2 * inch)
            story.append(rl_image)
            story.append(Spacer(1, 0.1 * inch))
            story.append(Paragraph("Scan the QR code to access the report online", body_style))

        doc.build(story)
        return buffer.getvalue()

    async def generate_qr_report(
        self,
        patient_id: str,
        scan_metadata: List[Dict[str, Any]],
        supabase_client: Any = None,
    ) -> Tuple[bytes, str, str]:
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
            Tuple[bytes, str, str]: A tuple containing:
                - The raw bytes of the final generated PDF report.
                - The secure, signed URL providing temporary access to the report.
                - The storage path identifier within the cloud bucket.

        Raises:
            RuntimeError: If the cloud storage provider fails to generate a signed access URL.
        """
        if supabase_client is None:
            raise RuntimeError("supabase_client must be provided")
        bucket = supabase_client.storage.from_("medical_reports")

        # 0. Fetch XAI images
        xai_images: Dict[str, bytes] = {}
        async with httpx.AsyncClient() as http_client:
            for m in scan_metadata:
                if m.get("xai_status") == "generated":
                    xai_url = build_xai_authenticated_url(m.get("xai_path"))
                    if xai_url:
                        # Use service role key to bypass user token context
                        try:
                            resp = await http_client.get(
                                xai_url,
                                headers={"Authorization": f"Bearer {gateway_config.supabase_secret_key}"},
                                timeout=10.0
                            )
                            if resp.status_code == 200:
                                xai_images[m.get("id")] = resp.content
                        except Exception:
                            pass

        # 0.5 Generate AI Summary
        ai_summary = None
        if scan_metadata:
            findings_list = "\n".join(
                f"{m.get('modality', 'UNKNOWN').upper()}: {m.get('ai_diagnosis', 'N/A')} ({_get_status(m.get('ai_diagnosis'), m.get('modality'))}, {m.get('confidence', 0.0) * 100:.1f}%)"
                for m in scan_metadata
            )
            prompt = (
                "Given these diagnostic findings from a patient's scans:\n"
                f"{findings_list}\n"
                "Write a short summary in 3-4 sentences, plain language. Do not state a\n"
                "diagnosis. Do not assert a causal relationship between findings unless\n"
                "there is a well-established, widely-recognized clinical association — and\n"
                "even then, phrase it as something a clinician should review, not as a\n"
                "determined fact. If there's nothing noteworthy connecting the findings,\n"
                "factually summarize what was found in each scan without inventing\n"
                "significance. End with a reminder that these results should be discussed\n"
                "with a qualified clinician."
            )
            ai_summary = await generate_hedged_text(prompt)

        # 1. Stage PDF without QR (so we can generate a signed URL)
        stage_pdf = self._build_pdf_story(patient_id, scan_metadata, xai_images, ai_summary=ai_summary)
        storage_path = f"{patient_id}_report.pdf"

        await bucket.upload(
            path=storage_path,
            file=stage_pdf,
            file_options={
                "content-type": "application/pdf",
                "x-upsert": "true",
            },
        )

        # 2. Obtain a signed URL pointing to the (still placeholder) object
        signed_resp = await bucket.create_signed_url(storage_path, 60 * 60 * 24)  # 24 hours
        signed_url = signed_resp.get("signedURL") or signed_resp.get("signedUrl")
        if not signed_url:
            raise RuntimeError("Could not create signed URL from Supabase")

        # 3. Build the final QR image encoding the signed URL
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(signed_url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")

        # 4. Build the final PDF that includes the QR image
        final_pdf = self._build_pdf_story(patient_id, scan_metadata, xai_images, ai_summary=ai_summary, qr_img=qr_img)

        # 5. Replace the placeholder object with the final PDF using x-upsert
        await bucket.upload(
            path=storage_path,
            file=final_pdf,
            file_options={
                "content-type": "application/pdf",
                "x-upsert": "true",
            },
        )

        return final_pdf, signed_url, storage_path
