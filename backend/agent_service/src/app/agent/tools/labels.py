from typing import Dict, Set

_NORMAL_LABELS: Dict[str, Set[str]] = {
    "cxr": {"No Finding"},
    "ecg": {"NORM"},
    "skin": {
        "Melanocytic nevi",
        "Benign keratosis-like lesions",
        "Dermatofibroma",
        "Vascular lesions",
    },
}

_ABNORMAL_LABELS: Dict[str, Set[str]] = {
    "cxr": {
        # CheXpert-14 pathologies
        "Enlarged Cardiomediastinum", "Cardiomegaly", "Lung Opacity",
        "Lung Lesion", "Edema", "Consolidation", "Pneumonia",
        "Atelectasis", "Pneumothorax", "Pleural Effusion",
        "Pleural Other", "Fracture",
        # hierarchical heads
        "Abnormal", "Fluid Accumulation", "Missing Lung Tissue",
        "Cardiac", "Opacity",
    },
    "ecg": {"MI", "STTC", "CD", "HYP"},
    "skin": {"Melanoma", "Basal cell carcinoma", "Actinic keratoses"},
}
