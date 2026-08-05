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
import logging
from datetime import datetime

import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table, TableStyle, PageBreak
from app.utils.xai_utils import build_xai_authenticated_url
import httpx
from app.core.config import gateway_config
from app.services.llm_service import generate_hedged_text
from app.utils.labels import _ABNORMAL_LABELS, _NORMAL_LABELS

logger = logging.getLogger(__name__)

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

    def _build_pdf_story(
        self,
        patient_id: str,
        scan_metadata: List[Dict[str, Any]],
        xai_images: Dict[str, bytes],
        original_images: Dict[str, bytes],
        ai_summary: Optional[str] = None,
        qr_img: Optional[Any] = None,
    ) -> bytes:
        """Constructs the PDF document layout and renders it to a byte stream."""
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
        caption_style = ParagraphStyle(
            'Caption',
            parent=styles['Italic'],
            fontSize=9,
            alignment=1,
            spaceAfter=12
        )
        story = []

        # Header
        story.append(Paragraph("MediScanX Clinical Report", title_style))
        story.append(Spacer(1, 0.1 * inch))
        
        header_data = [
            [Paragraph(f"<b>Patient ID:</b> {patient_id}", body_style)],
            [Paragraph(f"<b>Generated On:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", body_style)],
            [Paragraph(f"<b>Scans Included:</b> {len(scan_metadata)}", body_style)]
        ]
        header_table = Table(header_data, colWidths=[6.5 * inch])
        header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 0.2 * inch))

        if ai_summary is not None:
            story.append(Paragraph("AI-Generated Clinical Summary", styles["Heading3"]))
            story.append(Spacer(1, 0.05 * inch))
            story.append(Paragraph(ai_summary, body_style))
            story.append(Spacer(1, 0.05 * inch))
            disclaimer_text = "This summary is AI-generated and may be incomplete or inaccurate. It is not a diagnosis. Discuss these results with a qualified clinician."
            story.append(Paragraph(disclaimer_text, styles["Italic"]))
            story.append(Spacer(1, 0.2 * inch))

        # Scan metadata section
        story.append(Paragraph("Diagnostic Summary:", styles["Heading3"]))
        story.append(Spacer(1, 0.1 * inch))
        
        for i, m in enumerate(scan_metadata):
            if i > 0:
                story.append(PageBreak())
                
            scan_id = m.get('id', '?')
            confidence = m.get('confidence')
            conf_str = f"{confidence * 100:.0f}%" if confidence is not None else "N/A"
            
            scan_table_data = [
                ["Modality", m.get('modality', 'N/A').upper()],
                ["Diagnosis", m.get('ai_diagnosis', 'N/A')],
                ["Confidence", conf_str],
                ["Timestamp", m.get('timestamp', 'N/A')],
                ["Scan ID", scan_id]
            ]
            scan_table = Table(scan_table_data, colWidths=[1.5 * inch, 4.5 * inch])
            scan_table.setStyle(TableStyle([
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('PADDING', (0, 0), (-1, -1), 6),
            ]))
            story.append(scan_table)
            story.append(Spacer(1, 0.2 * inch))
            
            # Images
            images_data = []
            captions_data = []
            
            storage_path = m.get('storage_path')
            orig_img_bytes = original_images.get(scan_id)
            if orig_img_bytes:
                img_buffer = io.BytesIO(orig_img_bytes)
                rl_image = RLImage(img_buffer, width=3 * inch, height=3 * inch)
                images_data.append(rl_image)
                captions_data.append(Paragraph("Original Scan Image", caption_style))
            elif storage_path:
                images_data.append(Paragraph("<i>Original image failed to load.</i>", body_style))
                captions_data.append(Paragraph("", caption_style))
                
            xai_status = m.get('xai_status')
            if xai_status == 'generated':
                xai_img_bytes = xai_images.get(scan_id)
                if xai_img_bytes:
                    img_buffer = io.BytesIO(xai_img_bytes)
                    rl_image = RLImage(img_buffer, width=3 * inch, height=3 * inch)
                    images_data.append(rl_image)
                    captions_data.append(Paragraph("AI attention map — highlighted regions most influenced the model's assessment.", caption_style))
                else:
                    images_data.append(Paragraph("<i>Heatmap available but failed to load.</i>", body_style))
                    captions_data.append(Paragraph("", caption_style))
            else:
                images_data.append(Paragraph(f"<i>No heatmap is available for this scan (status: {xai_status}).</i>", body_style))
                captions_data.append(Paragraph("", caption_style))
                
            if images_data:
                if len(images_data) == 2:
                    img_table = Table([images_data, captions_data], colWidths=[3.2 * inch, 3.2 * inch])
                    img_table.setStyle(TableStyle([
                        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ]))
                    story.append(img_table)
                else:
                    for img, cap in zip(images_data, captions_data):
                        story.append(img)
                        story.append(cap)
            
            story.append(Spacer(1, 0.2 * inch))

        if qr_img is not None:
            story.append(Spacer(1, 0.3 * inch))
            qr_buffer = io.BytesIO()
            qr_img.save(qr_buffer, format="PNG")
            qr_buffer.seek(0)
            rl_image = RLImage(qr_buffer, width=1.5 * inch, height=1.5 * inch)
            story.append(rl_image)
            story.append(Spacer(1, 0.05 * inch))
            story.append(Paragraph("Scan the QR code to access the report online", styles["Italic"]))

        def add_footer(canvas, doc):
            canvas.saveState()
            
            # Watermark
            # Note: In SimpleDocTemplate, the page handler is called *after* 
            # the flowables are drawn, meaning this is drawn *over* the 
            # content. The high transparency (0.15 alpha) ensures it does 
            # not obscure diagnostic images or text.
            canvas.saveState()
            canvas.setFillColorRGB(0.5, 0.5, 0.5)
            canvas.setFillAlpha(0.15)
            canvas.setFont('Helvetica-Bold', 80)
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(45)
            canvas.drawCentredString(0, 0, "MediScanX")
            canvas.restoreState()

            canvas.setFont('Helvetica', 9)
            footer_text = f"Page {doc.page} | This document was produced by an AI diagnostic aid."
            canvas.drawString(inch, 0.75 * inch, footer_text)
            canvas.restoreState()

        doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
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
        stage_pdf = self._build_pdf_story(patient_id, scan_metadata, xai_images, original_images, ai_summary=ai_summary)
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

        # 3. Build the JWT token and the final QR image encoding the claim URL
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

        # 4. Build the final PDF that includes the QR image
        final_pdf = self._build_pdf_story(patient_id, scan_metadata, xai_images, original_images, ai_summary=ai_summary, qr_img=qr_img)

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
