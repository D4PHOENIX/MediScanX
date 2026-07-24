import json
import os
import pytest
import asyncpg
from pathlib import Path
from testcontainers.postgres import PostgresContainer

from app.agent.tools.rag_tool import search_clinical_guidelines
from langchain_core.runnables import RunnableConfig
from unittest.mock import patch

# Find the schema file robustly regardless of whether we are in backend/agent_service or agent_service
_repo_root = Path(__file__).resolve().parents[2]
if _repo_root.name == "backend":
    _repo_root = _repo_root.parent
SCHEMA_PATH = _repo_root / "schema" / "0007_updated_schema.sql"


@pytest.fixture(scope="module")
def postgres_container():
    with PostgresContainer("pgvector/pgvector:pg16") as postgres:
        yield postgres

@pytest.fixture(scope="function")
async def db_pool(postgres_container):
    # The testcontainers postgres gives us a connection string.
    url = postgres_container.get_connection_url()
    # It usually looks like postgresql+psycopg2://... we need postgresql:// for asyncpg
    if url.startswith("postgresql+psycopg2://"):
        url = url.replace("postgresql+psycopg2://", "postgresql://")
    
    # Bypass the session-scoped AsyncMock in conftest.py
    import importlib
    import sys
    real_asyncpg = importlib.reload(sys.modules['asyncpg'])
    pool = await real_asyncpg.create_pool(url, server_settings={'search_path': 'public, extensions, auth'})
    
    # Setup schema
    async with pool.acquire() as conn:
        # Create auth schema to satisfy Supabase dependencies
        await conn.execute("CREATE SCHEMA IF NOT EXISTS extensions;")
        await conn.execute("CREATE SCHEMA IF NOT EXISTS auth;")
        await conn.execute("CREATE TABLE IF NOT EXISTS auth.users (id UUID PRIMARY KEY, email TEXT, raw_user_meta_data JSONB);")
        await conn.execute("CREATE OR REPLACE FUNCTION auth.uid() RETURNS UUID AS $$ SELECT '00000000-0000-0000-0000-000000000000'::uuid $$ LANGUAGE sql;")
        
        # Set search path so vector type is found when it is created in extensions
        await conn.execute("SET search_path TO public, extensions, auth;")
        
        # Apply full schema
        with open(SCHEMA_PATH, "r") as f:
            schema_sql = f.read()
        
        # Testcontainers Postgres might run as a non-superuser, so extension creation might fail or need to be ignored
        # However, pgvector/pgvector usually has vector extension available or pre-installed.
        try:
            await conn.execute(schema_sql)
        except Exception as e:
            # If there's an error, maybe we need to drop the extension creation from schema_sql
            # Actually, we should just let it run.
            raise
            
        # Seed test data
        # Insert 1 glossary row
        await conn.execute("""
            INSERT INTO rag_corpus (title, content, source, external_id, specialty_tag, embedding)
            VALUES ($1, $2, $3, $4, $5, $6::halfvec(768))
        """, "Glossary Pneumonia", "Pneumonia is an infection.", "finding_glossary", "PNEUMONIA_GLOSSARY", "thoracic",
        "[" + ",".join(["0.1"] * 768) + "]")
        
        # We need the real query encoder to insert a vector that matches
        from transformers import AutoModel, AutoTokenizer
        import torch
        import torch.nn.functional as F
        
        tokenizer = AutoTokenizer.from_pretrained("ncbi/MedCPT-Article-Encoder")
        model = AutoModel.from_pretrained("ncbi/MedCPT-Article-Encoder")
        
        encoded = tokenizer("Treatment of pneumonia", truncation=True, padding=True, max_length=512, return_tensors='pt')
        outputs = model(**encoded)
        embeddings = outputs.last_hidden_state[:, 0, :]
        embeddings = F.normalize(embeddings, p=2, dim=1)
        general_vector_literal = "[" + ",".join(str(v) for v in embeddings[0].tolist()) + "]"

        # Insert 1 general row
        await conn.execute("""
            INSERT INTO rag_corpus (title, content, source, external_id, specialty_tag, embedding)
            VALUES ($1, $2, $3, $4, $5, $6::halfvec(768))
        """, "General Pneumonia Guidelines", "Treatment of pneumonia involves antibiotics.", "clinical_guidelines", "ext-1", "thoracic",
        general_vector_literal)

    yield pool
    await pool.close()

@pytest.mark.skipif(os.environ.get("CI") == "true", reason="Integration test requires local schema file which is not checked into version control")
@pytest.mark.asyncio
async def test_rag_integration_end_to_end(db_pool, auth_headers):
    config = RunnableConfig(configurable={"db_pool": db_pool})
    
    with patch("app.agent.tools.rag_tool._get_config") as mock_get_config:
        mock_cfg = mock_get_config.return_value
        # Use dummy url because we inject db_pool directly
        mock_cfg.database_url = "postgresql://user:pass@aws-0.pooler.supabase.com:5432/db"
        mock_cfg.rerank_enabled = False
        
        # Test 1: Finding label triggers glossary
        result_json = await search_clinical_guidelines.ainvoke(
            {"query": "Pneumonia details", "finding_label": "PNEUMONIA_GLOSSARY"},
            config
        )
        res = json.loads(result_json)
        assert len(res) >= 1
        assert res[0]["source"] == "finding_glossary"
        assert res[0]["external_id"] == "PNEUMONIA_GLOSSARY"
        
        # Test 2: General search using match_rag_corpus
        result_json2 = await search_clinical_guidelines.ainvoke(
            {"query": "Treatment of pneumonia"},
            config
        )
        res2 = json.loads(result_json2)
        assert len(res2) > 0
        assert res2[0]["source"] == "clinical_guidelines"
