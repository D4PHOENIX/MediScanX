import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock
import asyncpg

from app.agent.tools.fusion import fuse_multimodal_findings, orchestrate_fusion

@pytest.mark.asyncio
async def test_fusion_lowercase_cxr_ecg(auth_headers) -> None:
    """1. Rows with lowercase 'cxr' and 'ecg' produce a fused result."""
    result = await fuse_multimodal_findings.ainvoke(
        {
            "cxr_results": {"ai_diagnosis": "Pneumothorax", "confidence": 0.9},
            "ecg_results": {"ai_diagnosis": "MI", "confidence": 0.8},
        }
    )
    assert result["fusion_performed"] is True
    assert "CXR: Pneumothorax" in result["detected_conditions"]
    assert "ECG: MI" in result["detected_conditions"]


@pytest.mark.asyncio
async def test_fusion_normal_finding_no_alert(auth_headers) -> None:
    """2. No Finding at 0.95 confidence does not raise critical_alert."""
    result = await fuse_multimodal_findings.ainvoke(
        {
            "cxr_results": {"ai_diagnosis": "No Finding", "confidence": 0.95},
            "ecg_results": {"ai_diagnosis": "NORM", "confidence": 0.90},
        }
    )
    assert result["critical_alert"] is False
    assert result["aggregated_risk_score"] == 0.0


@pytest.mark.asyncio
async def test_fusion_two_abnormal_above_threshold(auth_headers) -> None:
    """3. An abnormal CXR at 0.95 alongside an abnormal ECG at 0.90 produces a score above threshold."""
    result = await fuse_multimodal_findings.ainvoke(
        {
            "cxr_results": {"ai_diagnosis": "Pneumothorax", "confidence": 0.95},
            "ecg_results": {"ai_diagnosis": "MI", "confidence": 0.90},
        }
    )
    # cxr weight = 1.2, conf = 0.95 -> 1.14
    # ecg weight = 1.5, conf = 0.90 -> 1.35
    # total weighted = 2.49 / 2.7 = 0.9222
    assert result["critical_alert"] is True
    assert result["aggregated_risk_score"] == pytest.approx(0.9222, abs=1e-3)


@pytest.mark.asyncio
async def test_fusion_reject_out_of_bounds_confidence(auth_headers) -> None:
    """4. confidence = 4.41 excludes that modality, does not clamp, and names it in the response."""
    result = await fuse_multimodal_findings.ainvoke(
        {
            "skin_results": {"ai_diagnosis": "Melanoma", "confidence": 4.41},
            "ecg_results": {"ai_diagnosis": "MI", "confidence": 0.9},
        }
    )
    # Skin is excluded, only ECG contributes. Since only ECG contributes, fusion_performed=False.
    assert result["fusion_performed"] is False
    assert any("4.41" in msg for msg in result.get("unscored", []))
    assert any("skin" in msg.lower() for msg in result.get("unscored", []))


@pytest.mark.asyncio
async def test_fusion_empty_ai_diagnosis(auth_headers) -> None:
    """5. An empty ai_diagnosis excludes that modality with a stated reason."""
    result = await fuse_multimodal_findings.ainvoke(
        {
            "cxr_results": {"ai_diagnosis": "", "confidence": 0.9},
            "ecg_results": {"ai_diagnosis": "MI", "confidence": 0.9},
        }
    )
    assert result["fusion_performed"] is False
    assert any("Empty ai_diagnosis" in msg for msg in result.get("unscored", []))
    assert any("cxr" in msg.lower() for msg in result.get("unscored", []))


@pytest.mark.asyncio
async def test_fusion_unrecognised_label(auth_headers) -> None:
    """6. An unrecognised label excludes that modality — asserted as not scored, not as scored-zero."""
    result = await fuse_multimodal_findings.ainvoke(
        {
            "cxr_results": {"ai_diagnosis": "Alien Virus", "confidence": 0.9},
            "ecg_results": {"ai_diagnosis": "MI", "confidence": 0.9},
        }
    )
    assert result["fusion_performed"] is False
    assert any("Unrecognised label" in msg for msg in result.get("unscored", []))
    assert any("Alien Virus" in msg for msg in result.get("unscored", []))
    # Score should just be ECG's score: 0.9 * 1.5 / 1.5 = 0.9
    assert result["aggregated_risk_score"] == pytest.approx(0.9, abs=1e-3)


@pytest.mark.asyncio
async def test_fusion_single_modality(auth_headers) -> None:
    """7. One contributing modality returns fusion_performed: false and no critical_alert."""
    result = await fuse_multimodal_findings.ainvoke(
        {
            "ecg_results": {"ai_diagnosis": "MI", "confidence": 0.99},
        }
    )
    assert result["fusion_performed"] is False
    assert result["critical_alert"] is False
    assert result["aggregated_risk_score"] == pytest.approx(0.99, abs=1e-3)


@pytest.mark.asyncio
async def test_orchestrate_fusion_modality_is_null(auth_headers) -> None:
    """8. A modality IS NULL row is excluded and reported."""
    from langchain_core.runnables import RunnableConfig
    
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = [
        {"scan_id": uuid.uuid4(), "modality": None, "ai_diagnosis": "MI", "confidence": 0.9},
        {"scan_id": uuid.uuid4(), "modality": "ecg", "ai_diagnosis": "MI", "confidence": 0.9},
    ]
    
    mock_acquire_ctx = MagicMock()
    mock_acquire_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_acquire_ctx
    
    config = RunnableConfig(configurable={"auth_user_id": str(uuid.uuid4()), "db_pool": mock_pool})
    result = await orchestrate_fusion.ainvoke({"selected_scan_ids": [str(uuid.uuid4()), str(uuid.uuid4())]}, config=config)
    
    assert "unscored" in result
    assert any("Modality IS NULL" in msg for msg in result["unscored"])
    assert "ecg_results" in result


@pytest.mark.asyncio
async def test_orchestrate_fusion_isolation(auth_headers) -> None:
    """9. A scan belonging to another user_id is not returned."""
    from langchain_core.runnables import RunnableConfig
    
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = []
    
    mock_acquire_ctx = MagicMock()
    mock_acquire_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_acquire_ctx
    
    dummy_user_id = str(uuid.uuid4())
    config = RunnableConfig(configurable={"auth_user_id": dummy_user_id, "db_pool": mock_pool})
    
    result = await orchestrate_fusion.ainvoke({"selected_scan_ids": [str(uuid.uuid4())]}, config=config)
    
    assert "No valid scans found" in result["message"]
    mock_conn.fetch.assert_called_once()
    query = mock_conn.fetch.call_args[0][0]
    args = mock_conn.fetch.call_args[0][1:]
    assert "user_id = $2" in query
    assert str(args[1]) == dummy_user_id


@pytest.mark.asyncio
async def test_orchestrate_fusion_missing_column(auth_headers) -> None:
    """10. A query against a missing column raises rather than returning a message string."""
    from langchain_core.runnables import RunnableConfig
    
    mock_conn = AsyncMock()
    mock_conn.fetch.side_effect = asyncpg.exceptions.UndefinedColumnError("column 'does_not_exist' does not exist")
    
    mock_acquire_ctx = MagicMock()
    mock_acquire_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_acquire_ctx
    
    config = RunnableConfig(configurable={"auth_user_id": str(uuid.uuid4()), "db_pool": mock_pool})
    
    with pytest.raises(RuntimeError):
        await orchestrate_fusion.ainvoke({"selected_scan_ids": [str(uuid.uuid4())]}, config=config)


@pytest.mark.asyncio
async def test_orchestrate_fusion_duplicate_modality(auth_headers) -> None:
    """11. Duplicate modality returns a correctable message and does not fuse."""
    from langchain_core.runnables import RunnableConfig
    
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = [
        {"scan_id": uuid.uuid4(), "modality": "cxr", "ai_diagnosis": "Pneumonia", "confidence": 0.9},
        {"scan_id": uuid.uuid4(), "modality": "cxr", "ai_diagnosis": "No Finding", "confidence": 0.9},
    ]
    
    mock_acquire_ctx = MagicMock()
    mock_acquire_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_acquire_ctx
    
    config = RunnableConfig(configurable={"auth_user_id": str(uuid.uuid4()), "db_pool": mock_pool})
    
    result = await orchestrate_fusion.ainvoke({"selected_scan_ids": [str(uuid.uuid4()), str(uuid.uuid4())]}, config=config)
    
    assert "message" in result
    assert "Multiple cxr scans were selected" in result["message"]
    assert "cxr_results" not in result
