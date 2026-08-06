"""Visual constants for the generated clinical report.

One accent colour, used only where it carries meaning (clinical severity).
Everything else is a restrained ink/muted/rule palette. Decorative colour in a
clinical document competes with the one signal that matters.
"""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4

INK = colors.HexColor("#1A2332")      # near-black with a blue cast; softer than #000
MUTED = colors.HexColor("#5A6B7C")    # secondary text
FAINT = colors.HexColor("#8A97A3")    # tertiary — record identifiers
RULE = colors.HexColor("#DDE3E9")     # hairlines and table borders
PANEL = colors.HexColor("#F4F7F9")    # tinted panel background
ACCENT = colors.HexColor("#0F5A73")   # brand teal, section headers only

SEVERITY = {
    "abnormal": colors.HexColor("#C0392B"),
    "normal": colors.HexColor("#2E7D5B"),
    "unknown": colors.HexColor("#B8860B"),
}

SEVERITY_LABEL = {
    "abnormal": "ABNORMAL",
    "normal": "NORMAL",
    "unknown": "UNCLASSIFIED",
}

MODALITY_NAMES = {
    "cxr": "Chest X-Ray",
    "ecg": "Electrocardiogram",
    "skin": "Skin Lesion",
}

PAGE_MARGIN = 54  # 0.75in — tighter than the 1in default; more room without crowding
CONTENT_W = A4[0] - (PAGE_MARGIN * 2)

# patient_records.full_name is NOT NULL but carries this sentinel for accounts
# created without a profile. It must not reach the page as if it were a name.
PLACEHOLDER_NAMES = {"unknown user", "unknown", ""}
