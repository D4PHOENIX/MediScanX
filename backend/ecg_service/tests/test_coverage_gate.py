"""Tests for the ECG Coverage Gate."""

import pytest
import numpy as np
import cv2
from unittest.mock import patch

from app.engine.preprocessor import ECGPreprocessor
from app.core.config import Settings
from app.core.exceptions import ECGExtractionError


def test_preprocessor_coverage_gate() -> None:
    cfg = Settings()
    preprocessor = ECGPreprocessor(cfg)

    # Construct a synthetic binary array representing 12 sliced leads
    lead_order = [
        'I', 'aVR', 'V1', 'V4',
        'II', 'aVL', 'V2', 'V5',
        'III', 'aVF', 'V3', 'V6',
    ]

    width, height = 100, 100
    
    # Create perfect leads
    perfect_lead = np.zeros((height, width), dtype=np.uint8)
    cv2.line(perfect_lead, (0, 50), (99, 50), 255, 1)

    lead_images = {lead: perfect_lead.copy() for lead in lead_order}
    assert len(lead_images) == 12, f"Expected 12 leads, got {len(lead_images)}"

    with patch.object(preprocessor._remover, "remove_grid", return_value=np.zeros((100, 100))), \
         patch.object(preprocessor._slicer, "slice_image", return_value=lead_images):
         
        # 1. Coverage above threshold on all leads passes
        tensor, _ = preprocessor.process_image("fake_path")
        assert tensor.shape == (1, 12, 250)
        
        # 2. A single lead below threshold raises ECGExtractionError
        bad_lead = np.zeros((height, width), dtype=np.uint8)
        cv2.line(bad_lead, (0, 50), (19, 50), 255, 1)
        lead_images['V3'] = bad_lead

        with pytest.raises(ECGExtractionError) as exc_info:
            preprocessor.process_image("fake_path")
        
        # 3. The reported per-lead coverage figures match the constructed input
        assert 'V3' in exc_info.value.context['leads_failed']
        assert exc_info.value.context['coverage']['V3'] == 0.20
        assert exc_info.value.context['coverage']['I'] == 1.0

        # 4. A lead where interpolation fails on span still reports its true coverage, not 0.0
        # With the relaxed span check (span < 50%), we must provide a short trace.
        span_fail_lead = np.zeros((height, width), dtype=np.uint8)
        cv2.line(span_fail_lead, (5, 50), (45, 50), 255, 1)
        
        lead_images['V3'] = perfect_lead  # Reset V3
        lead_images['II'] = span_fail_lead

        with pytest.raises(ECGExtractionError) as exc_info2:
            preprocessor.process_image("fake_path")

        assert 'II' in exc_info2.value.context['leads_failed']
        assert exc_info2.value.context['coverage']['II'] == 0.41
