import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.scan_persistence_service import ScanPersistenceService

@pytest.mark.asyncio
async def test_insert_scan_result_executes_correct_query():
    # Setup mock pool and connection
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    
    # We mock the async context manager for pool.acquire()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = None
    
    # Setup mock execute to return "INSERT 0 1" (successful insertion)
    mock_conn.execute.return_value = "INSERT 0 1"
    
    metadata = {"model_version": "v1.2", "bbox": [0,0,10,10]}
    
    result = await ScanPersistenceService.insert_scan_result(
        pool=mock_pool,
        scan_id="scan-uuid-123",
        user_id="user-uuid-456",
        scan_type=1,
        scan_status=2,
        image_url="https://example.com/image.jpg",
        ai_diagnosis="Pneumonia",
        confidence=0.95,
        inference_source="cloud",
        doctor_id="doc-uuid-789",
        findings="Consolidation in lower right lobe",
        metadata=metadata,
    )
    
    assert result is True
    
    # Assert incoming scan data is actually written to `scan_results` with expected columns/values.
    # Note on RLS / security scoping:
    # RLS/security scoping ("persisted securely") is NOT testable at this layer.
    # The scan_persistence_service uses a shared backend asyncpg connection pool that bypasses user-specific 
    # session variables for RLS during insert. The scoping is enforced by explicitly passing `user_id` as a parameter ($2) 
    # into the query rather than via Row-Level Security session context. 
    # Thus, rejecting a write to the wrong user isn't handled by this Python layer; it would be handled by DB constraints or auth endpoints higher up.
    
    mock_conn.execute.assert_awaited_once()
    args = mock_conn.execute.await_args[0]
    
    # The first arg is the query string
    query = args[0]
    assert "INSERT INTO scan_results" in query
    assert "ON CONFLICT (scan_id) DO NOTHING" in query
    
    # The remaining args are the values ($1 to $11)
    # 1: scan_id
    assert args[1] == "scan-uuid-123"
    # 2: user_id
    assert args[2] == "user-uuid-456"
    # 3: doctor_id
    assert args[3] == "doc-uuid-789"
    # 4: scan_type
    assert args[4] == 1
    # 5: scan_status
    assert args[5] == 2
    # 6: image_url
    assert args[6] == "https://example.com/image.jpg"
    # 7: ai_diagnosis
    assert args[7] == "Pneumonia"
    # 8: findings
    assert args[8] == "Consolidation in lower right lobe"
    # 9: confidence
    assert args[9] == 0.95
    # 10: metadata (json dump)
    assert args[10] == json.dumps(metadata)
    # 11: inference_source
    assert args[11] == "cloud"

@pytest.mark.asyncio
async def test_insert_scan_result_conflict_returns_false():
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = None
    
    # Simulate conflict where DO NOTHING results in no rows inserted
    mock_conn.execute.return_value = "INSERT 0 0"
    
    result = await ScanPersistenceService.insert_scan_result(
        pool=mock_pool,
        scan_id="scan-123",
        user_id="user-456",
        scan_type=0,
        scan_status=0,
        image_url="url",
        ai_diagnosis="Normal",
        confidence=0.99,
        inference_source="edge"
    )
    
    assert result is False
