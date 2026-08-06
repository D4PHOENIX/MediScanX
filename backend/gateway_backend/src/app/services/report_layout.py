"""ReportLab layout for the clinical report PDF.

Owns every visual decision — styles, flowables, page furniture. Knows nothing
about the database, storage, or the LLM; it receives fully-resolved values and
renders them.

Layout follows the ordering used by standard radiology reporting practice:
patient demographics, study/technique, findings, then impression.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Image as RLImage, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
    Spacer, Table, TableStyle,
)

from app.services.report_format import (
    _get_status, fmt_timestamp, format_dob, modality_name, record_no,
    resolve_display_name, study_line,
)
from app.services.report_theme import (
    ACCENT, CONTENT_W, FAINT, INK, MUTED, PAGE_MARGIN, PANEL, RULE, SEVERITY,
    SEVERITY_LABEL,
)

logger = logging.getLogger(__name__)


def build_styles() -> Dict[str, ParagraphStyle]:
    """Every text style used in the document, in one place."""
    base = getSampleStyleSheet()
    return {
        "wordmark": ParagraphStyle(
            "Wordmark", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=19, leading=22, textColor=INK),
        "subtitle": ParagraphStyle(
            "Subtitle", parent=base["Normal"], fontName="Helvetica",
            fontSize=9, leading=12, textColor=MUTED),
        "meta_label": ParagraphStyle(
            "MetaLabel", parent=base["Normal"], fontName="Helvetica",
            fontSize=7.5, leading=10, textColor=MUTED, alignment=2),
        "meta_value": ParagraphStyle(
            "MetaValue", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=9, leading=12, textColor=INK, alignment=2),
        "section": ParagraphStyle(
            "Section", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=9.5, leading=12, textColor=ACCENT, spaceAfter=2),
        "section_note": ParagraphStyle(
            "SectionNote", parent=base["Normal"], fontName="Helvetica",
            fontSize=7.5, leading=10, textColor=MUTED),
        "patient": ParagraphStyle(
            "PatientName", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=17, leading=21, textColor=INK),
        "body": ParagraphStyle(
            "Body", parent=base["Normal"], fontName="Helvetica",
            fontSize=9.5, leading=14, textColor=INK),
        "disclaimer": ParagraphStyle(
            "Disclaimer", parent=base["Normal"], fontName="Helvetica-Oblique",
            fontSize=7.5, leading=10.5, textColor=MUTED),
        "field_label": ParagraphStyle(
            "FieldLabel", parent=base["Normal"], fontName="Helvetica",
            fontSize=7.5, leading=10, textColor=MUTED),
        "field_value": ParagraphStyle(
            "FieldValue", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=10, leading=13, textColor=INK),
        "headline": ParagraphStyle(
            "Headline", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=15, leading=19, textColor=INK),
        "record_id": ParagraphStyle(
            "RecordId", parent=base["Normal"], fontName="Courier",
            fontSize=6.5, leading=9, textColor=FAINT),
        "caption": ParagraphStyle(
            "Caption", parent=base["Normal"], fontName="Helvetica",
            fontSize=7.5, leading=10, textColor=MUTED, alignment=1),
        "absent": ParagraphStyle(
            "Absent", parent=base["Normal"], fontName="Helvetica-Oblique",
            fontSize=8, leading=11, textColor=MUTED, alignment=1),
        "th": ParagraphStyle(
            "TH", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=7.5, leading=10, textColor=MUTED),
        "td": ParagraphStyle(
            "TD", parent=base["Normal"], fontName="Helvetica",
            fontSize=9, leading=12, textColor=INK),
    }


def hairline(width: float = CONTENT_W, thickness: float = 0.5, color=RULE) -> Table:
    """A flat rule. Used for section underlines and the closing divider."""
    t = Table([[""]], colWidths=[width], rowHeights=[thickness])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def severity_chip(status: str) -> Table:
    """A solid severity badge. Colour is reserved exclusively for this."""
    chip = Table(
        [[SEVERITY_LABEL.get(status, "UNCLASSIFIED")]],
        colWidths=[1.15 * inch],
        rowHeights=[0.22 * inch],
    )
    chip.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SEVERITY.get(status, SEVERITY["unknown"])),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return chip


def fit_image(img_bytes: bytes, max_w: float, max_h: float) -> Optional[RLImage]:
    """Scale an image into a box while preserving its aspect ratio.

    A fixed square would distort both portrait chest films and wide ECG strips.
    Diagnostic imagery must not be stretched.
    """
    try:
        reader = ImageReader(io.BytesIO(img_bytes))
        iw, ih = reader.getSize()
        if not iw or not ih:
            return None
        scale = min(max_w / iw, max_h / ih)
        return RLImage(io.BytesIO(img_bytes), width=iw * scale, height=ih * scale)
    except Exception as exc:
        logger.warning(f"Could not render embedded image: {exc}")
        return None


def _section(title: str, s: Dict[str, ParagraphStyle], note: Optional[str] = None) -> List[Any]:
    """Section header with a hairline beneath — the document's only rhythm."""
    if note:
        head = Table(
            [[Paragraph(title.upper(), s["section"]), Paragraph(note, s["section_note"])]],
            colWidths=[CONTENT_W - 2.2 * inch, 2.2 * inch],
        )
        head.setStyle(TableStyle([
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        return [head, hairline(), Spacer(1, 9)]
    return [Paragraph(title.upper(), s["section"]), hairline(), Spacer(1, 9)]


def _masthead(s: Dict[str, ParagraphStyle], report_record_no: Optional[str]) -> List[Any]:
    """Left-aligned wordmark and report meta.

    A centred title reads as a certificate; a masthead reads as a document.
    """
    meta_rows = [
        [Paragraph("REPORT DATE", s["meta_label"])],
        [Paragraph(datetime.now().strftime("%d %b %Y, %H:%M"), s["meta_value"])],
    ]
    if report_record_no:
        meta_rows.append([Paragraph("REPORT NO.", s["meta_label"])])
        meta_rows.append([Paragraph(report_record_no, s["meta_value"])])

    meta_tbl = Table(meta_rows, colWidths=[1.9 * inch])
    meta_tbl.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))

    masthead = Table(
        [[
            [Paragraph("MediScanX", s["wordmark"]),
             Paragraph("Clinical Diagnostic Report", s["subtitle"])],
            meta_tbl,
        ]],
        colWidths=[CONTENT_W - 1.9 * inch, 1.9 * inch],
    )
    masthead.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return [masthead, hairline(thickness=2, color=ACCENT), Spacer(1, 16)]


def _patient_panel(
    s: Dict[str, ParagraphStyle],
    display_name: str,
    patient_info: Optional[Dict[str, Any]],
    patient_record_no: str,
) -> Table:
    """Name-led demographics block.

    Fields are omitted individually when absent rather than rendered empty or
    as the word "Unknown".
    """
    cells: List[Any] = []

    dob_text = format_dob(patient_info.get("date_of_birth")) if patient_info else None
    if dob_text:
        cells.append([Paragraph("DATE OF BIRTH", s["field_label"]),
                      Paragraph(dob_text, s["field_value"])])

    gender_text = (patient_info.get("gender") or "").strip() if patient_info else ""
    if gender_text:
        cells.append([Paragraph("SEX", s["field_label"]),
                      Paragraph(gender_text, s["field_value"])])

    cells.append([Paragraph("RECORD NO.", s["field_label"]),
                  Paragraph(patient_record_no, s["field_value"])])

    col_w = (CONTENT_W - 24) / max(len(cells), 1)
    demo_row = Table([cells], colWidths=[col_w] * len(cells))
    demo_row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    panel = Table(
        [[Paragraph(display_name, s["patient"])], [Spacer(1, 8)], [demo_row]],
        colWidths=[CONTENT_W],
    )
    panel.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (0, 0), 11),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 12),
        ("TOPPADDING", (0, 1), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -2), 0),
    ]))
    return panel


def _findings_table(s: Dict[str, ParagraphStyle], scan_metadata: List[Dict[str, Any]]) -> Table:
    """Severity-coded overview.

    Placed before the narrative: a clinician reading a referral wants to know
    what was found and how severe before reading prose about it.
    """
    rows: List[List[Any]] = [[
        Paragraph("MODALITY", s["th"]),
        Paragraph("FINDING", s["th"]),
        Paragraph("CONFIDENCE", s["th"]),
        Paragraph("ASSESSMENT", s["th"]),
    ]]

    for m in scan_metadata:
        status = _get_status(m.get("ai_diagnosis"), m.get("modality"))
        conf = m.get("confidence")
        rows.append([
            Paragraph(modality_name(m.get("modality")), s["td"]),
            Paragraph(m.get("ai_diagnosis") or "No finding reported", s["td"]),
            Paragraph(f"{conf * 100:.0f}%" if conf is not None else "—", s["td"]),
            severity_chip(status),
        ])

    table = Table(
        rows,
        colWidths=[1.35 * inch, CONTENT_W - (1.35 + 1.0 + 1.35) * inch,
                   1.0 * inch, 1.35 * inch],
    )
    style = [
        ("LINEBELOW", (0, 0), (-1, 0), 0.75, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
    ]
    for r in range(1, len(rows) - 1):
        style.append(("LINEBELOW", (0, r), (-1, r), 0.25, RULE))
    table.setStyle(TableStyle(style))
    return table


def _impression_block(s: Dict[str, ParagraphStyle], ai_summary: str) -> Table:
    """Summary and disclaimer inside one accent-barred block.

    They share a container so a future edit cannot separate the disclaimer from
    the text it qualifies.
    """
    body_block = Table(
        [
            [Paragraph(ai_summary, s["body"])],
            [Spacer(1, 7)],
            [Paragraph(
                "This summary is AI-generated and may be incomplete or inaccurate. "
                "It is not a diagnosis. Discuss these results with a qualified clinician.",
                s["disclaimer"],
            )],
        ],
        colWidths=[CONTENT_W - 14],
    )
    body_block.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    barred = Table([["", body_block]], colWidths=[3, CONTENT_W - 3])
    barred.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), ACCENT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 0),
        ("LEFTPADDING", (1, 0), (1, 0), 11),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return barred


def _scan_detail(
    s: Dict[str, ParagraphStyle],
    m: Dict[str, Any],
    index: int,
    total: int,
    xai_images: Dict[str, bytes],
    original_images: Dict[str, bytes],
) -> List[Any]:
    """One scan: headline finding, metadata row, and paired imagery."""
    scan_id = m.get("id", "?")
    confidence = m.get("confidence")
    conf_str = f"{confidence * 100:.0f}%" if confidence is not None else "—"
    status = _get_status(m.get("ai_diagnosis"), m.get("modality"))

    out: List[Any] = _section("Scan Detail", s, f"{index + 1} of {total}")

    headline = Table(
        [[
            [Paragraph(modality_name(m.get("modality")).upper(), s["field_label"]),
             Paragraph(m.get("ai_diagnosis") or "No finding reported", s["headline"])],
            severity_chip(status),
        ]],
        colWidths=[CONTENT_W - 1.35 * inch, 1.35 * inch],
    )
    headline.setStyle(TableStyle([
        ("VALIGN", (0, 0), (0, 0), "TOP"),
        ("VALIGN", (1, 0), (1, 0), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    out.append(headline)

    detail = Table(
        [[
            [Paragraph("CONFIDENCE", s["field_label"]), Paragraph(conf_str, s["field_value"])],
            [Paragraph("ACQUIRED", s["field_label"]),
             Paragraph(fmt_timestamp(m.get("timestamp")), s["field_value"])],
            [Paragraph("SCAN REFERENCE", s["field_label"]),
             Paragraph(record_no(scan_id, "SCN"), s["field_value"])],
        ]],
        colWidths=[1.2 * inch, 1.9 * inch, CONTENT_W - 3.1 * inch],
    )
    detail.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("LINEABOVE", (0, 0), (-1, 0), 0.25, RULE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.25, RULE),
    ]))
    out.append(detail)
    out.append(Spacer(1, 14))

    box_w = (CONTENT_W - 18) / 2
    box_h = 3.0 * inch

    def cell(img_bytes: Optional[bytes], absent_text: str) -> Any:
        if img_bytes:
            fitted = fit_image(img_bytes, box_w, box_h)
            if fitted is not None:
                return fitted
        return Paragraph(absent_text, s["absent"])

    left_cell = cell(
        original_images.get(scan_id),
        "Original image could not be retrieved." if m.get("storage_path")
        else "No source image on record.",
    )

    xai_status = m.get("xai_status")
    if xai_status == "generated":
        right_cell = cell(xai_images.get(scan_id), "Attention map could not be retrieved.")
        right_caption = ("Attention map — warmer regions carry greater "
                         "influence on the model's assessment.")
    else:
        right_cell = Paragraph(
            f"No attention map available for this scan ({xai_status}).", s["absent"])
        right_caption = ""

    img_row = Table(
        [
            [left_cell, right_cell],
            [Paragraph("Source image", s["caption"]), Paragraph(right_caption, s["caption"])],
        ],
        colWidths=[box_w, box_w],
    )
    img_row.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
        ("VALIGN", (0, 1), (-1, 1), "TOP"),
        ("BACKGROUND", (0, 0), (0, 0), PANEL),
        ("BACKGROUND", (1, 0), (1, 0), PANEL),
        ("TOPPADDING", (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
        ("TOPPADDING", (0, 1), (-1, 1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    out.append(img_row)
    return out


def _access_panel(s: Dict[str, ParagraphStyle], qr_img: Any) -> Any:
    """QR grouped with its explanation so the two never split across a page."""
    qr_buffer = io.BytesIO()
    qr_img.save(qr_buffer, format="PNG")
    qr_buffer.seek(0)

    access = Table(
        [[
            RLImage(qr_buffer, width=1.35 * inch, height=1.35 * inch),
            [
                Paragraph("SECURE ACCESS", s["field_label"]),
                Spacer(1, 3),
                Paragraph(
                    "Scan this code with the MediScanX app to open this report. "
                    "A clinician scanning it will also receive time-limited access "
                    "to this patient's diagnostic history.",
                    s["body"],
                ),
            ],
        ]],
        colWidths=[1.7 * inch, CONTENT_W - 1.7 * inch],
    )
    access.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, 0), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
    ]))
    return KeepTogether(access)


def _decorate_page(canvas, doc) -> None:
    """Watermark and footer, drawn on every page.

    SimpleDocTemplate invokes page handlers after flowables are drawn, so the
    watermark lands over the content. Alpha is kept very low and the mark small
    so it cannot tint a diagnostic image — legibility of the imagery outweighs
    the prominence of the mark.
    """
    canvas.saveState()

    canvas.saveState()
    canvas.setFillColor(INK)
    canvas.setFillAlpha(0.045)
    canvas.setFont("Helvetica-Bold", 58)
    canvas.translate(A4[0] / 2, A4[1] / 2)
    canvas.rotate(45)
    canvas.drawCentredString(0, 0, "MediScanX")
    canvas.restoreState()

    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(PAGE_MARGIN, 52, A4[0] - PAGE_MARGIN, 52)

    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(
        PAGE_MARGIN, 40,
        "Produced by an AI diagnostic aid. Not a substitute for clinical judgement.",
    )
    canvas.drawRightString(A4[0] - PAGE_MARGIN, 40, f"Page {doc.page}")

    canvas.restoreState()


def build_pdf_story(
    patient_id: str,
    scan_metadata: List[Dict[str, Any]],
    xai_images: Dict[str, bytes],
    original_images: Dict[str, bytes],
    ai_summary: Optional[str] = None,
    qr_img: Optional[Any] = None,
    report_id: Optional[str] = None,
    patient_info: Optional[Dict[str, Any]] = None,
) -> bytes:
    """Assemble the document and render it to PDF bytes."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=PAGE_MARGIN,
        leftMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN,
        bottomMargin=PAGE_MARGIN + 18,  # clearance for the footer rule
        title="MediScanX Clinical Report",
        author="MediScanX",
    )

    s = build_styles()
    patient_record_no = record_no(patient_id, "MSX")
    report_record_no = record_no(report_id, "RPT") if report_id else None
    display_name = resolve_display_name(patient_info, patient_record_no)

    story: List[Any] = []
    story.extend(_masthead(s, report_record_no))
    story.append(_patient_panel(s, display_name, patient_info, patient_record_no))
    story.append(Spacer(1, 10))

    study = Table(
        [[Paragraph("STUDY", s["field_label"]),
          Paragraph(study_line(scan_metadata), s["body"])]],
        colWidths=[0.75 * inch, CONTENT_W - 0.75 * inch],
    )
    study.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(study)
    story.append(Spacer(1, 8))

    if scan_metadata:
        story.extend(_section("Findings", s))
        story.append(_findings_table(s, scan_metadata))
        story.append(Spacer(1, 18))

    if ai_summary is not None:
        story.extend(_section("Impression", s, "AI-generated"))
        story.append(_impression_block(s, ai_summary))
        story.append(Spacer(1, 18))

    for i, m in enumerate(scan_metadata):
        story.append(PageBreak())
        story.extend(_scan_detail(s, m, i, len(scan_metadata), xai_images, original_images))

    if qr_img is not None:
        story.append(Spacer(1, 22))
        story.append(_access_panel(s, qr_img))

    # Full UUIDs are retained for traceability — they are what match this
    # document back to a record — but set small and last so they do not
    # compete with the patient's name.
    story.append(Spacer(1, 16))
    story.append(hairline(thickness=0.25))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"Patient record: {patient_id}", s["record_id"]))
    if report_id:
        story.append(Paragraph(f"Report record: {report_id}", s["record_id"]))
    for m in scan_metadata:
        story.append(Paragraph(
            f"Scan {record_no(m.get('id'), 'SCN')}: {m.get('id')}", s["record_id"]))

    doc.build(story, onFirstPage=_decorate_page, onLaterPages=_decorate_page)
    return buffer.getvalue()
