import pytest
from app.services.scan_persistence_service import ScanPersistenceService

def test_derive_scan_status_live_skin_case():
    # Melanocytic nevi / skin / 0.9953 -> 0
    assert ScanPersistenceService.derive_scan_status(0.9953, ai_diagnosis="Melanocytic nevi", modality="skin") == 0

def test_derive_scan_status_normal_cxr():
    # No Finding / cxr / 0.99 -> 0
    assert ScanPersistenceService.derive_scan_status(0.99, ai_diagnosis="No Finding", modality="cxr") == 0

def test_derive_scan_status_abnormal_high_risk():
    # A genuine abnormal label at >= _HIGH_RISK_THRESHOLD -> 2
    assert ScanPersistenceService.derive_scan_status(0.85, ai_diagnosis="Melanoma", modality="skin") == 2
    assert ScanPersistenceService.derive_scan_status(0.90, ai_diagnosis="MI", modality="ecg") == 2

def test_derive_scan_status_abnormal_warning():
    # The same abnormal label just below _HIGH_RISK_THRESHOLD -> 1
    assert ScanPersistenceService.derive_scan_status(0.84, ai_diagnosis="Melanoma", modality="skin") == 1

def test_derive_scan_status_abnormal_normal_confidence():
    # The same abnormal label below _WARNING_THRESHOLD -> 0
    assert ScanPersistenceService.derive_scan_status(0.49, ai_diagnosis="Melanoma", modality="skin") == 0

def test_derive_scan_status_unrecognised_label():
    # Unrecognised label + valid modality -> 1, at both high and low confidence. Assert it is 1 at 0.99 specifically.
    assert ScanPersistenceService.derive_scan_status(0.99, ai_diagnosis="Some Unknown Disease", modality="skin") == 1
    assert ScanPersistenceService.derive_scan_status(0.10, ai_diagnosis="Some Unknown Disease", modality="skin") == 1

def test_derive_scan_status_empty_or_none_diagnosis():
    # ai_diagnosis=None -> 1. Empty string -> 1
    assert ScanPersistenceService.derive_scan_status(0.99, ai_diagnosis=None, modality="skin") == 1
    assert ScanPersistenceService.derive_scan_status(0.99, ai_diagnosis="", modality="skin") == 1

def test_derive_scan_status_modality_none():
    # modality=None with a recognised-looking label -> 1
    assert ScanPersistenceService.derive_scan_status(0.99, ai_diagnosis="Melanoma", modality=None) == 1

