import pytest
import uuid
import json
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
    mock_acquire_ctx.__aexit__ = AsyncMock()
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

def test_temporal_and_metrics_tools_not_registered():
    """Verify that calculate_temporal_progression and query_patient_metrics are not exposed to the agent."""
    from app.agent.graph import TOOLS
    tool_names = [t.name for t in TOOLS]
    assert "calculate_temporal_progression" not in tool_names
    assert "query_patient_metrics" not in tool_names
