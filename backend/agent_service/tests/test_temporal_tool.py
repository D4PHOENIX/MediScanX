import pytest
import uuid
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from langchain_core.runnables import RunnableConfig

@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer fake"}

@pytest.mark.asyncio
async def test_list_recent_scans_caller_owned(auth_headers) -> None:
    """Verify that list_recent_scans enforces the user_id constraint."""
    from app.agent.tools.temporal import list_recent_scans
    
    dummy_user_id = str(uuid.uuid4())
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = []
    
    mock_acquire_ctx = MagicMock()
    mock_acquire_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_acquire_ctx
    
    config = RunnableConfig(configurable={"auth_user_id": dummy_user_id, "db_pool": mock_pool})
    
    result = await list_recent_scans.ainvoke({"limit": 5}, config=config)
    assert "No recent scans found" in result
    
    mock_conn.fetch.assert_called_once()
    query = mock_conn.fetch.call_args[0][0]
    args = mock_conn.fetch.call_args[0][1:]
    
    assert "user_id = $1" in query
    assert args[0] == uuid.UUID(dummy_user_id)
    assert args[1] == 5

def test_temporal_and_metrics_tools_are_registered():
    """Verify that calculate_temporal_progression and query_patient_metrics are exposed to the agent."""
    from app.agent.graph import TOOLS
    tool_names = [t.name for t in TOOLS]
    assert "calculate_temporal_progression" in tool_names
    assert "query_patient_metrics" in tool_names

from app.agent.tools.temporal import calculate_temporal_progression, list_recent_scans

def _setup_mock_config(auth_user_id: str, fetchrow_returns=None, fetch_returns=None, fetchrow_side_effect=None):
    mock_conn = AsyncMock()
    if fetchrow_side_effect:
        mock_conn.fetchrow.side_effect = fetchrow_side_effect
    else:
        mock_conn.fetchrow.return_value = fetchrow_returns
        
    mock_conn.fetch.return_value = fetch_returns or []
    
    mock_acquire_ctx = MagicMock()
    mock_acquire_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_acquire_ctx
    return RunnableConfig(configurable={"auth_user_id": auth_user_id, "db_pool": mock_pool})

@pytest.mark.asyncio
async def test_normal_to_abnormal_returns_worsening():
    user_id = str(uuid.uuid4())
    curr_id = str(uuid.uuid4())
    prev_id = str(uuid.uuid4())
    
    def side_effect(query, *args):
        if curr_id in str(args):
            return {"scan_id": curr_id, "modality": "cxr", "ai_diagnosis": "Pneumonia", "confidence": 0.9, "scan_date": datetime(2023, 2, 1)}
        return {"scan_id": prev_id, "modality": "cxr", "ai_diagnosis": "No Finding", "confidence": 0.9, "scan_date": datetime(2023, 1, 1)}
        
    config = _setup_mock_config(user_id, fetchrow_side_effect=side_effect)
    res = await calculate_temporal_progression.ainvoke({"current_scan_id": curr_id, "previous_scan_id": prev_id}, config=config)
    assert res["direction"] == "worsening"

@pytest.mark.asyncio
async def test_abnormal_to_normal_returns_improving():
    user_id = str(uuid.uuid4())
    curr_id = str(uuid.uuid4())
    prev_id = str(uuid.uuid4())
    
    def side_effect(query, *args):
        if curr_id in str(args):
            return {"scan_id": curr_id, "modality": "cxr", "ai_diagnosis": "No Finding", "confidence": 0.9, "scan_date": datetime(2023, 2, 1)}
        return {"scan_id": prev_id, "modality": "cxr", "ai_diagnosis": "Pneumonia", "confidence": 0.9, "scan_date": datetime(2023, 1, 1)}
        
    config = _setup_mock_config(user_id, fetchrow_side_effect=side_effect)
    res = await calculate_temporal_progression.ainvoke({"current_scan_id": curr_id, "previous_scan_id": prev_id}, config=config)
    assert res["direction"] == "improving"

@pytest.mark.asyncio
async def test_abnormal_to_different_abnormal_returns_changed():
    user_id = str(uuid.uuid4())
    curr_id = str(uuid.uuid4())
    prev_id = str(uuid.uuid4())
    
    def side_effect(query, *args):
        if curr_id in str(args):
            return {"scan_id": curr_id, "modality": "cxr", "ai_diagnosis": "Edema", "confidence": 0.9, "scan_date": datetime(2023, 2, 1)}
        return {"scan_id": prev_id, "modality": "cxr", "ai_diagnosis": "Pneumonia", "confidence": 0.9, "scan_date": datetime(2023, 1, 1)}
        
    config = _setup_mock_config(user_id, fetchrow_side_effect=side_effect)
    res = await calculate_temporal_progression.ainvoke({"current_scan_id": curr_id, "previous_scan_id": prev_id}, config=config)
    assert res["direction"] == "changed"

@pytest.mark.asyncio
async def test_same_label_both_scans_returns_unchanged():
    user_id = str(uuid.uuid4())
    curr_id = str(uuid.uuid4())
    prev_id = str(uuid.uuid4())
    
    def side_effect(query, *args):
        if curr_id in str(args):
            return {"scan_id": curr_id, "modality": "cxr", "ai_diagnosis": "Pneumonia", "confidence": 0.95, "scan_date": datetime(2023, 2, 1)}
        return {"scan_id": prev_id, "modality": "cxr", "ai_diagnosis": "Pneumonia", "confidence": 0.8, "scan_date": datetime(2023, 1, 1)}
        
    config = _setup_mock_config(user_id, fetchrow_side_effect=side_effect)
    res = await calculate_temporal_progression.ainvoke({"current_scan_id": curr_id, "previous_scan_id": prev_id}, config=config)
    assert res["direction"] == "unchanged"

@pytest.mark.asyncio
async def test_normal_to_different_normal_returns_unchanged():
    user_id = str(uuid.uuid4())
    curr_id = str(uuid.uuid4())
    prev_id = str(uuid.uuid4())
    
    def side_effect(query, *args):
        if curr_id in str(args):
            return {"scan_id": curr_id, "modality": "skin", "ai_diagnosis": "Melanocytic nevi", "confidence": 0.9, "scan_date": datetime(2023, 2, 1)}
        return {"scan_id": prev_id, "modality": "skin", "ai_diagnosis": "Dermatofibroma", "confidence": 0.9, "scan_date": datetime(2023, 1, 1)}
        
    config = _setup_mock_config(user_id, fetchrow_side_effect=side_effect)
    res = await calculate_temporal_progression.ainvoke({"current_scan_id": curr_id, "previous_scan_id": prev_id}, config=config)
    assert res["direction"] == "unchanged"

@pytest.mark.asyncio
async def test_unrecognised_label_returns_indeterminate():
    user_id = str(uuid.uuid4())
    curr_id = str(uuid.uuid4())
    prev_id = str(uuid.uuid4())
    
    def side_effect(query, *args):
        if curr_id in str(args):
            return {"scan_id": curr_id, "modality": "cxr", "ai_diagnosis": "UnknownPathology", "confidence": 0.9, "scan_date": datetime(2023, 2, 1)}
        return {"scan_id": prev_id, "modality": "cxr", "ai_diagnosis": "Pneumonia", "confidence": 0.9, "scan_date": datetime(2023, 1, 1)}
        
    config = _setup_mock_config(user_id, fetchrow_side_effect=side_effect)
    res = await calculate_temporal_progression.ainvoke({"current_scan_id": curr_id, "previous_scan_id": prev_id}, config=config)
    assert res["direction"] == "indeterminate"
    assert "unrecognised" in res["interpretation"]

@pytest.mark.asyncio
async def test_large_confidence_delta_does_not_change_direction():
    user_id = str(uuid.uuid4())
    curr_id = str(uuid.uuid4())
    prev_id = str(uuid.uuid4())
    
    def side_effect(query, *args):
        if curr_id in str(args):
            return {"scan_id": curr_id, "modality": "cxr", "ai_diagnosis": "Pneumonia", "confidence": 0.99, "scan_date": datetime(2023, 2, 1)}
        return {"scan_id": prev_id, "modality": "cxr", "ai_diagnosis": "Pneumonia", "confidence": 0.10, "scan_date": datetime(2023, 1, 1)}
        
    config = _setup_mock_config(user_id, fetchrow_side_effect=side_effect)
    res = await calculate_temporal_progression.ainvoke({"current_scan_id": curr_id, "previous_scan_id": prev_id}, config=config)
    assert res["direction"] == "unchanged"
    assert res["confidence_delta"] == 0.89

@pytest.mark.asyncio
async def test_no_prior_scan_returns_message():
    user_id = str(uuid.uuid4())
    curr_id = str(uuid.uuid4())
    
    def side_effect(query, *args):
        if "ORDER BY scan_date DESC" in query:
            return None
        return {"scan_id": curr_id, "modality": "cxr", "ai_diagnosis": "Pneumonia", "confidence": 0.9, "scan_date": datetime(2023, 2, 1)}
        
    config = _setup_mock_config(user_id, fetchrow_side_effect=side_effect)
    res = await calculate_temporal_progression.ainvoke({"current_scan_id": curr_id}, config=config)
    assert "No prior scan of modality 'cxr' found" in res["interpretation"]
    assert "direction" not in res

@pytest.mark.asyncio
async def test_explicit_previous_scan_different_modality_refused():
    user_id = str(uuid.uuid4())
    curr_id = str(uuid.uuid4())
    prev_id = str(uuid.uuid4())
    
    def side_effect(query, *args):
        if curr_id in str(args):
            return {"scan_id": curr_id, "modality": "cxr", "ai_diagnosis": "Pneumonia", "confidence": 0.9, "scan_date": datetime(2023, 2, 1)}
        return {"scan_id": prev_id, "modality": "ecg", "ai_diagnosis": "MI", "confidence": 0.9, "scan_date": datetime(2023, 1, 1)}
        
    config = _setup_mock_config(user_id, fetchrow_side_effect=side_effect)
    res = await calculate_temporal_progression.ainvoke({"current_scan_id": curr_id, "previous_scan_id": prev_id}, config=config)
    assert "Cannot compare scans of different modalities" in res["interpretation"]

@pytest.mark.asyncio
async def test_malformed_scan_id_returns_message():
    user_id = str(uuid.uuid4())
    config = _setup_mock_config(user_id)
    res = await calculate_temporal_progression.ainvoke({"current_scan_id": "not-a-uuid"}, config=config)
    assert "Invalid current_scan_id format" in res["interpretation"]

@pytest.mark.asyncio
async def test_scan_belonging_to_another_user_is_not_returned():
    user_id = str(uuid.uuid4())
    curr_id = str(uuid.uuid4())
    
    def side_effect(query, *args):
        return None
        
    config = _setup_mock_config(user_id, fetchrow_side_effect=side_effect)
    res = await calculate_temporal_progression.ainvoke({"current_scan_id": curr_id}, config=config)
    assert "not found or does not belong to the user" in res["interpretation"]

@pytest.mark.asyncio
async def test_failed_query_raises_rather_than_returning_string():
    user_id = str(uuid.uuid4())
    curr_id = str(uuid.uuid4())
    
    import asyncpg
    def side_effect(query, *args):
        raise asyncpg.exceptions.UndefinedColumnError("column id does not exist")
        
    config = _setup_mock_config(user_id, fetchrow_side_effect=side_effect)
    with pytest.raises(asyncpg.exceptions.UndefinedColumnError):
        await calculate_temporal_progression.ainvoke({"current_scan_id": curr_id}, config=config)

@pytest.mark.asyncio
async def test_list_recent_scans_returns_modality_not_scan_type():
    user_id = str(uuid.uuid4())
    scan_id = str(uuid.uuid4())
    
    mock_row = {"scan_id": uuid.UUID(scan_id), "modality": "cxr", "scan_status": "completed", "scan_date": datetime(2023, 2, 1), "ai_diagnosis": "Pneumonia", "confidence": 0.9}
    config = _setup_mock_config(user_id, fetch_returns=[mock_row])
    
    res_str = await list_recent_scans.ainvoke({"limit": 5}, config=config)
    res = json.loads(res_str)
    
    assert len(res) == 1
    assert "modality" in res[0]
    assert "scan_type" not in res[0]
