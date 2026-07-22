import pytest
from unittest.mock import AsyncMock, patch
import app.agent.tools.temporal  # Load module before patch

@pytest.mark.asyncio
@patch("app.agent.tools.temporal.asyncpg.connect", new_callable=AsyncMock)
@patch.dict("os.environ", {"DATABASE_URL": "postgresql://test:test@aws-0-eu-central-1.pooler.supabase.com:5432/test"})
async def test_query_patient_metrics(mock_connect: AsyncMock) -> None:
    """Test the query_patient_metrics tool returns formatted newline-separated output."""
    from app.agent.tools.temporal import query_patient_metrics

    mock_conn = AsyncMock()
    mock_connect.return_value = mock_conn

    # Mock successful fetch from patient_metrics table
    mock_conn.fetchrow.return_value = {
        "id": "row-1",
        "patient_id": "P123",
        "age": 45,
        "heart_rate": 72,
        "blood_pressure": "120/80",
        "created_at": None,
        "updated_at": None,
    }

    result = await query_patient_metrics.ainvoke({"patient_id": "P123"})

    # Verify actual newlines (not escaped \\n) are present
    assert "\n" in result, "Output must contain real newline characters, not escaped \\\\n"
    assert "Metrics for patient" in result
    assert "age: 45" in result
    assert "heart_rate: 72" in result
    assert "blood_pressure: 120/80" in result

    # Test fallback exception handling
    mock_conn.fetchrow.side_effect = Exception("DB error")
    result_error = await query_patient_metrics.ainvoke({"patient_id": "P123"})
    assert "An error occurred" in result_error
