import pytest
from fastapi import HTTPException
from app.services.scan_persistence_service import ScanPersistenceService
from app.utils.labels import _NORMAL_LABELS, _ABNORMAL_LABELS

def test_derive_scan_status_live_skin_case():
    assert ScanPersistenceService.derive_scan_status(0.9953, ai_diagnosis="Melanocytic nevi", modality="skin") == 2

def test_derive_scan_status_normal_cxr():
    assert ScanPersistenceService.derive_scan_status(0.99, ai_diagnosis="No Finding", modality="cxr") == 0

def test_derive_scan_status_abnormal_high_risk():
    assert ScanPersistenceService.derive_scan_status(0.85, ai_diagnosis="Melanoma", modality="skin") == 2
    assert ScanPersistenceService.derive_scan_status(0.90, ai_diagnosis="MI", modality="ecg") == 2

def test_derive_scan_status_abnormal_warning():
    assert ScanPersistenceService.derive_scan_status(0.84, ai_diagnosis="Melanoma", modality="skin") == 1

def test_derive_scan_status_abnormal_normal_confidence():
    # The same abnormal label below _WARNING_THRESHOLD -> 1 (used to be 0)
    assert ScanPersistenceService.derive_scan_status(0.49, ai_diagnosis="Melanoma", modality="skin") == 1

def test_derive_scan_status_unrecognised_label():
    # Unrecognised label + valid modality -> raises HTTP 500
    with pytest.raises(HTTPException) as exc_info:
        ScanPersistenceService.derive_scan_status(0.99, ai_diagnosis="Some Unknown Disease", modality="skin")
    assert exc_info.value.status_code == 500
    assert "Some Unknown Disease" in exc_info.value.detail
    assert "skin" in exc_info.value.detail

def test_derive_scan_status_empty_or_none_diagnosis():
    assert ScanPersistenceService.derive_scan_status(0.99, ai_diagnosis=None, modality="skin") == 1
    assert ScanPersistenceService.derive_scan_status(0.99, ai_diagnosis="", modality="skin") == 1

def test_derive_scan_status_modality_none():
    assert ScanPersistenceService.derive_scan_status(0.99, ai_diagnosis="Melanoma", modality=None) == 1

# Parametrized tests across all modalities
def _generate_abnormal_cases():
    cases = []
    for mod in ["cxr", "ecg", "skin"]:
        for label in _ABNORMAL_LABELS.get(mod, set()):
            cases.append((mod, label))
    return cases

@pytest.mark.parametrize("modality, label", _generate_abnormal_cases())
def test_all_abnormal_labels(modality, label):
    assert ScanPersistenceService.derive_scan_status(0.30, ai_diagnosis=label, modality=modality) == 1
    assert ScanPersistenceService.derive_scan_status(0.60, ai_diagnosis=label, modality=modality) == 1
    assert ScanPersistenceService.derive_scan_status(0.90, ai_diagnosis=label, modality=modality) == 2

def _generate_normal_cases():
    cases = []
    for mod in ["cxr", "ecg", "skin"]:
        for label in _NORMAL_LABELS.get(mod, set()):
            cases.append((mod, label))
    return cases

@pytest.mark.parametrize("modality, label", _generate_normal_cases())
def test_all_normal_labels(modality, label):
    assert ScanPersistenceService.derive_scan_status(0.99, ai_diagnosis=label, modality=modality) == 0
    assert ScanPersistenceService.derive_scan_status(0.10, ai_diagnosis=label, modality=modality) == 0

def test_explicit_cases():
    # skin "Basal cell carcinoma" at 0.45 -> 1
    assert ScanPersistenceService.derive_scan_status(0.45, ai_diagnosis="Basal cell carcinoma", modality="skin") == 1
    # cxr "Support Devices" and "Other" -> non-zero with no exception
    assert ScanPersistenceService.derive_scan_status(0.10, ai_diagnosis="Support Devices", modality="cxr") == 1
    assert ScanPersistenceService.derive_scan_status(0.90, ai_diagnosis="Other", modality="cxr") == 2
