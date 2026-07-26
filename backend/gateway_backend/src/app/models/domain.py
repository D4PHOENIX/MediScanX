"""Domain enumerations for medical diagnostic modalities.

This module provides strict enumerations for the types of medical data
supported by the MediScanX Gateway, ensuring type safety when routing
requests to downstream inference microservices.
"""

from enum import Enum


class ModalityType(str, Enum):
    """Enumeration of supported medical imaging and diagnostic modalities.

    This enumeration defines the primary classes of diagnostic data processed
    by the downstream machine learning microservices. It is utilized to validate
    incoming payloads and direct them to the appropriate processing queue.
    """

    CXR = "CXR"
    ECG = "ECG"
    SKIN = "SKIN"

class ScanModality(str, Enum):
    """Database-aligned enumeration for scan modality values.
    
    Used to set the 'modality' column in scan_results.
    """
    
    CXR = "cxr"
    ECG = "ecg"
    SKIN = "skin"
