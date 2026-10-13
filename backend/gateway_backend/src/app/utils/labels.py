"""Clinical labels configuration.

NOTE: This is a gateway-local copy of the label set.
The definitive source of truth is `agent_service/src/app/agent/tools/labels.py`.
These two files MUST be updated together to ensure cross-service consistency.
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
