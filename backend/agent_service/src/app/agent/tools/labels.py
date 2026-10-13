"""Clinical labels configuration — agent_service copy.

NOTE: This is the definitive source of truth for the label set.
The gateway copy at `gateway_backend/src/app/utils/labels.py` MUST be kept
in sync with this file.
"""
from typing import Dict, Set

_NORMAL_LABELS: Dict[str, Set[str]] = {
    "cxr": {"No Finding"},
    "ecg": {"NORM"},
    "skin": {"Normal skin"},
}

_ABNORMAL_LABELS: Dict[str, Set[str]] = {
    "cxr": {
        # CheXpert-14 pathologies
        "Enlarged Cardiomediastinum", "Cardiomegaly", "Lung Opacity",
        "Lung Lesion", "Edema", "Consolidation", "Pneumonia",
        "Atelectasis", "Pneumothorax", "Pleural Effusion",
        "Pleural Other", "Fracture", "Support Devices",
        # hierarchical heads
        "Abnormal", "Fluid Accumulation", "Missing Lung Tissue",
        "Cardiac", "Opacity", "Other",
    },
    "ecg": {"MI", "STTC", "CD", "HYP"},
    "skin": {
        "Actinic keratoses",
        "Basal cell carcinoma",
        "Benign keratosis-like lesions",
        "Dermatofibroma",
        "Melanocytic nevi",
        "Melanoma",
        "Vascular lesions",
    },
}
