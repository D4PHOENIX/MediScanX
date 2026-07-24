import pytest

@pytest.mark.asyncio
async def test_fuse_multimodal_findings_critical_alert(auth_headers) -> None:
    """Verify that a high ECG confidence triggers the critical alert.

    Math verification (normalized scoring):
        ECG weight = 1.5, max_prob = 0.92
        weighted_score = 0.92 × 1.5 = 1.38
        applied_weight = 1.5
        normalized = 1.38 / 1.5 = 0.92
        0.92 >= 0.85 → critical_alert = True
    """
    from app.agent.tools.fusion import fuse_multimodal_findings

    result = await fuse_multimodal_findings.ainvoke(
        {
            "ecg_results": {
                "predicted_class": "AFIB",
                "probabilities": {"AFIB": 0.92, "Normal": 0.08},
            }
        }
    )
    # ECG weight = 1.5, max_prob = 0.92 → normalized = 0.92 / 1.0 = 0.92
    assert result["critical_alert"] is True
    assert "ECG: AFIB" in result["detected_conditions"]
    # After normalization: 0.92 * 1.5 / 1.5 = 0.92
    assert result["aggregated_risk_score"] == pytest.approx(0.92, abs=1e-4)
    assert result["aggregated_risk_score"] <= 1.0, "Risk score must not exceed 1.0"


@pytest.mark.asyncio
async def test_fuse_multimodal_findings_no_alert(auth_headers) -> None:
    """Verify that a low-confidence skin finding does not trigger a critical alert."""
    from app.agent.tools.fusion import fuse_multimodal_findings

    result = await fuse_multimodal_findings.ainvoke(
        {
            "skin_results": {
                "predicted_class": "Benign",
                "probabilities": {"Benign": 0.50, "Malignant": 0.50},
            }
        }
    )
    # Skin weight = 1.0, max_prob = 0.50 → normalized = 0.50 / 1.0 = 0.50
    assert result["critical_alert"] is False
    assert result["aggregated_risk_score"] == pytest.approx(0.5, abs=1e-4)
    assert result["aggregated_risk_score"] <= 1.0


@pytest.mark.asyncio
async def test_fuse_multimodal_findings_multi_modality(auth_headers) -> None:
    """Verify normalized risk score across multiple modalities.

    Math verification:
        ECG: max_prob=0.92, weight=1.5 → weighted=1.38
        CXR: max_prob=0.80, weight=1.2 → weighted=0.96
        sum_weighted = 1.38 + 0.96 = 2.34
        sum_weights = 1.5 + 1.2 = 2.7
        normalized = 2.34 / 2.7 ≈ 0.8667
        0.8667 >= 0.85 → critical_alert = True
    """
    from app.agent.tools.fusion import fuse_multimodal_findings

    result = await fuse_multimodal_findings.ainvoke(
        {
            "ecg_results": {
                "predicted_class": "AFIB",
                "probabilities": {"AFIB": 0.92, "Normal": 0.08},
            },
            "cxr_results": {
                "predicted_class": "Cardiomegaly",
                "probabilities": {"Cardiomegaly": 0.80, "Normal": 0.20},
            },
        }
    )
    expected_score = (0.92 * 1.5 + 0.80 * 1.2) / (1.5 + 1.2)
    assert result["aggregated_risk_score"] == pytest.approx(expected_score, abs=1e-4)
    assert result["critical_alert"] is True
    assert result["aggregated_risk_score"] <= 1.0, "Normalized score must be in [0, 1]"
    assert len(result["detected_conditions"]) == 2


@pytest.mark.asyncio
async def test_fuse_multimodal_findings_all_modalities_bounded(auth_headers) -> None:
    """Verify risk score is bounded to [0.0, 1.0] when all modalities contribute.

    Even with high confidence across all modalities, normalization keeps
    the score within the probability range.
    """
    from app.agent.tools.fusion import fuse_multimodal_findings

    result = await fuse_multimodal_findings.ainvoke(
        {
            "ecg_results": {
                "predicted_class": "VT",
                "probabilities": {"VT": 0.99, "Normal": 0.01},
            },
            "cxr_results": {
                "predicted_class": "Pneumothorax",
                "probabilities": {"Pneumothorax": 0.95, "Normal": 0.05},
            },
            "skin_results": {
                "predicted_class": "Melanoma",
                "probabilities": {"Melanoma": 0.98, "Benign": 0.02},
            },
        }
    )
    # All weights: ECG=1.5, CXR=1.2, Skin=1.0 → sum=3.7
    # Weighted: 0.99*1.5 + 0.95*1.2 + 0.98*1.0 = 1.485 + 1.14 + 0.98 = 3.605
    # Normalized: 3.605 / 3.7 ≈ 0.9743
    expected = (0.99 * 1.5 + 0.95 * 1.2 + 0.98 * 1.0) / (1.5 + 1.2 + 1.0)
    assert result["aggregated_risk_score"] == pytest.approx(expected, abs=1e-4)
    assert 0.0 <= result["aggregated_risk_score"] <= 1.0
    assert result["critical_alert"] is True
    assert len(result["detected_conditions"]) == 3
