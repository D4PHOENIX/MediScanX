"""Value formatting and prompt construction for the clinical report.

Pure functions only: no ReportLab, no database, no I/O. Everything here turns a
stored value into something a person reads, or builds the impression prompt.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from app.services.report_theme import MODALITY_NAMES, PLACEHOLDER_NAMES
from app.utils.labels import _ABNORMAL_LABELS, _NORMAL_LABELS


def _get_status(label: Optional[str], mod: Optional[str]) -> str:
    """Classify a finding as normal, abnormal, or unclassified."""
    if not label or not mod:
        return "unknown"
    if label in _NORMAL_LABELS.get(mod, set()):
        return "normal"
    if label in _ABNORMAL_LABELS.get(mod, set()):
        return "abnormal"
    return "unknown"


def fmt_timestamp(ts: Optional[str]) -> str:
    """Render an ISO timestamp as something a person reads, not a log line."""
    if not ts or ts == "N/A":
        return "—"
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y, %H:%M UTC")
    except (ValueError, TypeError):
        return str(ts)


def fmt_date_only(ts: Optional[str]) -> Optional[str]:
    """Date without time, for the study line. None when unparseable."""
    if not ts or ts == "N/A":
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y")
    except (ValueError, TypeError):
        return None


def record_no(uuid_str: Optional[str], prefix: str) -> str:
    """A short, human-readable record number derived from a UUID.

    Clinical reports identify a patient by a short record number, not by an
    internal key. The full UUID is retained elsewhere in the document.
    """
    if not uuid_str:
        return "—"
    stem = str(uuid_str).replace("-", "")[:8].upper()
    return f"{prefix}-{stem}"


def format_dob(dob_raw: Optional[str]) -> Optional[str]:
    """Format 'YYYY-MM-DD' as '03 Apr 2005 (21y)'.

    Returns None when absent or unparseable so the caller can omit the field
    entirely rather than rendering an empty one or the word "Unknown".
    """
    if not dob_raw:
        return None
    try:
        dob = date.fromisoformat(str(dob_raw).strip()[:10])
    except (ValueError, TypeError):
        return None
    today = date.today()
    years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    if years < 0 or years > 130:
        return dob.strftime("%d %b %Y")
    return f"{dob.strftime('%d %b %Y')} ({years}y)"


def modality_name(code: Optional[str]) -> str:
    """Human-readable modality, falling back to the raw code."""
    key = (code or "").lower()
    return MODALITY_NAMES.get(key, (key or "—").upper())


def resolve_display_name(patient_info: Optional[Dict[str, Any]], fallback: str) -> str:
    """Prefer full name, then username, then the record number."""
    if patient_info:
        full = (patient_info.get("full_name") or "").strip()
        if full and full.lower() not in PLACEHOLDER_NAMES:
            return full
        uname = (patient_info.get("username") or "").strip()
        if uname:
            return uname
    return fallback


def study_line(scan_metadata: List[Dict[str, Any]]) -> str:
    """One-line study description, following the radiology 'technique' convention."""
    if not scan_metadata:
        return "No scans included"

    count = len(scan_metadata)
    noun = "diagnostic scan" if count == 1 else "diagnostic scans"

    seen: List[str] = []
    for m in scan_metadata:
        name = modality_name(m.get("modality"))
        if name not in seen:
            seen.append(name)
    modalities = ", ".join(seen) if seen else "Unspecified"

    raw = sorted(
        str(m.get("timestamp")) for m in scan_metadata
        if m.get("timestamp") not in (None, "N/A")
    )
    if raw:
        first = fmt_date_only(raw[0])
        last = fmt_date_only(raw[-1])
        when = f"acquired {first}" if first == last else f"acquired {first} – {last}"
    else:
        when = "acquisition date unavailable"

    return f"{count} {noun} · {modalities} · {when}"


def build_impression_prompt(scan_metadata: List[Dict[str, Any]]) -> str:
    """Build the prompt for the report's Impression section.

    The findings list includes each scan's computed assessment so the model
    cannot describe a finding as reassuring while the severity chip beside it
    reads ABNORMAL.
    """
    findings_list = "\n".join(
        f"- {modality_name(m.get('modality'))}: "
        f"{m.get('ai_diagnosis') or 'no finding reported'} "
        f"(assessment: {_get_status(m.get('ai_diagnosis'), m.get('modality'))}, "
        f"model confidence {(m.get('confidence') or 0.0) * 100:.1f}%)"
        for m in scan_metadata
    )
    return (
        "You are writing the Impression section of a clinical diagnostic report "
        "that will be read by both a patient and a clinician.\n\n"
        "Findings from the patient's scans:\n"
        f"{findings_list}\n\n"
        "Write four to six sentences of flowing prose covering, in order:\n"
        "1. What was examined, in plain language.\n"
        "2. What was found in each scan, naming the finding and briefly explaining "
        "what part of the body or what feature it refers to.\n"
        "3. What the model's confidence figure does and does not mean — it reflects "
        "how strongly the pattern matched, not how severe or certain a condition is.\n"
        "4. What the reader should do next.\n\n"
        "Constraints, all of which are mandatory:\n"
        "- Do not state a diagnosis.\n"
        "- Do not assert a causal relationship between findings unless there is a "
        "well-established, widely-recognised clinical association — and even then, "
        "phrase it as something a clinician should review, not as a determined fact.\n"
        "- If nothing meaningfully connects the findings, summarise each factually "
        "without inventing significance.\n"
        "- Do not invent clinical detail that is not in the findings above: no "
        "symptoms, no medical history, no severity the data does not support.\n"
        "- Do not describe a finding as normal or reassuring when its assessment is "
        "abnormal, and do not describe an abnormal finding as alarming beyond what "
        "the assessment states. Match the assessment given for each finding.\n"
        "- End by directing the reader to discuss the results with a qualified "
        "clinician.\n\n"
        "Write plainly. No headings, no bullet points, no markdown."
    )
