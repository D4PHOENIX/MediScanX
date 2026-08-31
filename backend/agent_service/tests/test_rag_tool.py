"""Tests for rag_tool.py."""

import json
import math
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

from langchain_core.runnables import RunnableConfig
from app.agent.tools.rag_tool import search_clinical_guidelines
from app.core.embedding_contract import EMBEDDING_DIM

@pytest.mark.asyncio
async def test_rag_query_encoder_and_retrieval(monkeypatch, auth_headers):
    # This test hits both the _embed wrapper and the retrieval logic
    # without a finding_label.
    
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value = ctx
    
    # Mock return rows for search
    mock_conn.fetch.return_value = [
        {
            "id": "doc-1",
            "title": "Test Guideline",
            "content": "This is a test guideline for thoracic context.",
            "similarity": 0.85,
            "source": "clinical_guidelines",
            "external_id": "ext-1"
        }
    ]

    config = RunnableConfig(configurable={"db_pool": mock_pool})
    
    # Force rerank_enabled=False to avoid running the cross-encoder in this test
    with patch("app.agent.tools.rag_tool._get_config") as mock_get_config:
        # Instead of mocking AgentConfig directly, we return a mock object
        mock_cfg = mock_get_config.return_value
        mock_cfg.database_url = "postgresql://user:pass@aws-0.pooler.supabase.com:5432/db"
        mock_cfg.rerank_enabled = False
        
        result_json = await search_clinical_guidelines.ainvoke(
            {"query": "pneumonia treatment guidelines"},
            config
        )
    
    # 1. Assert _embed behavior
    # fetch is called with query: f"SELECT id, title, content, source, external_id, metadata, similarity FROM match_rag_corpus($1::halfvec({EMBEDDING_DIM}), 0.1, 20, NULL, 'thoracic')"
    # and the vector literal
    assert mock_conn.fetch.called
    call_args = mock_conn.fetch.call_args[0]
    query_str = call_args[0]
    vector_literal = call_args[1]
    
    # Verify the SQL call
    expected_sql = f"SELECT id, title, content, source, external_id, metadata, similarity FROM match_rag_corpus($1::halfvec({EMBEDDING_DIM}), 0.1, 20, NULL, 'thoracic')"
    assert query_str == expected_sql
    
    # Verify the embedded vector literal
    assert vector_literal.startswith("[") and vector_literal.endswith("]")
    vector_list = json.loads(vector_literal)
    
    # Assert output shape
    assert len(vector_list) == EMBEDDING_DIM
    assert len(vector_list) == 768
    
    # Assert output is L2-normalized
    norm = math.sqrt(sum(v * v for v in vector_list))
    assert math.isclose(norm, 1.0, rel_tol=1e-4)

    # 2. Assert return JSON includes source and external_id
    res = json.loads(result_json)
    assert len(res) == 1
    assert res[0]["source"] == "clinical_guidelines"
    assert res[0]["external_id"] == "ext-1"


@pytest.mark.asyncio
async def test_rag_finding_label_glossary_lookup(monkeypatch, auth_headers):
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value = ctx
    
    mock_conn.fetchrow.return_value = {
        "id": "gloss-1",
        "title": "Glossary Entry",
        "content": "Glossary definition",
        "source": "finding_glossary",
        "external_id": "AFIB_LABEL"
    }
    
    mock_conn.fetch.return_value = [] # no general results

    config = RunnableConfig(configurable={"db_pool": mock_pool})
    
    with patch("app.agent.tools.rag_tool._get_config") as mock_get_config:
        mock_cfg = mock_get_config.return_value
        mock_cfg.database_url = "postgresql://user:pass@aws-0.pooler.supabase.com:5432/db"
        mock_cfg.rerank_enabled = False
        
        result_json = await search_clinical_guidelines.ainvoke(
            {"query": "AFIB details", "finding_label": "AFIB_LABEL"},
            config
        )
        
    assert mock_conn.fetchrow.called
    fetchrow_call = mock_conn.fetchrow.call_args[0]
    expected_glossary_query = "SELECT id, title, content, source, external_id FROM rag_corpus WHERE source='finding_glossary' AND external_id=$1 LIMIT 1"
    assert fetchrow_call[0] == expected_glossary_query
    assert fetchrow_call[1] == "AFIB_LABEL"
    
    res = json.loads(result_json)
    assert len(res) == 1
    assert res[0]["id"] == "gloss-1"
    assert res[0]["source"] == "finding_glossary"
    assert res[0]["external_id"] == "AFIB_LABEL"
    assert res[0]["similarity"] == 1.0


@pytest.mark.asyncio
async def test_rag_rerank_enabled(auth_headers):
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value = ctx
    
    # We will return 6 documents to ensure truncation to top 5
    docs = []
    for i in range(6):
        docs.append({
            "id": f"doc-{i}",
            "title": f"Doc {i}",
            "content": f"Content for doc {i}",
            "similarity": 0.5,
            "source": "test",
            "external_id": f"ext-{i}"
        })
    mock_conn.fetch.return_value = docs

    config = RunnableConfig(configurable={"db_pool": mock_pool})
    
    with patch("app.agent.tools.rag_tool._get_config") as mock_get_config:
        mock_cfg = mock_get_config.return_value
        mock_cfg.database_url = "postgresql://user:pass@aws-0.pooler.supabase.com:5432/db"
        mock_cfg.rerank_enabled = True
        
        result_json = await search_clinical_guidelines.ainvoke(
            {"query": "rerank test"},
            config
        )
        
    # Should truncate to 5
    res = json.loads(result_json)
    assert len(res) == 5
