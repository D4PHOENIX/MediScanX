-- ==============================================================================
-- MediScanX - Migration 0004
-- File: 0004_recreate_rag_corpus.sql
-- Description: Drops the legacy "medical_documents" table and creates the new
--              "rag_corpus" table from scratch. This is a destructive migration
--              that wipes the old 768-d vector embeddings, paving the way for 
--              a clean re-seeding with the new 384-d halfvec schema.
-- ==============================================================================

BEGIN;

DROP TABLE IF EXISTS medical_documents CASCADE;
DROP TABLE IF EXISTS rag_corpus CASCADE; -- Just in case it was partially created

CREATE TABLE rag_corpus (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    embedding halfvec(384),
    title TEXT,
    source TEXT NOT NULL DEFAULT 'PubMedQA',
    external_id TEXT NOT NULL DEFAULT '',
    specialty_tag TEXT DEFAULT 'thoracic',
    
    -- Idempotent upsert constraint
    CONSTRAINT uq_rag_corpus_source_external_id UNIQUE (source, external_id)
);

CREATE INDEX idx_rag_corpus_embedding 
    ON rag_corpus USING hnsw (embedding halfvec_cosine_ops);

ALTER TABLE rag_corpus ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read access to RAG corpus" ON rag_corpus
    FOR SELECT TO public USING (true);

CREATE OR REPLACE FUNCTION match_rag_corpus (
    query_embedding halfvec(384),
    match_threshold float,
    match_count int
)
RETURNS TABLE (
    id uuid,
    content text,
    metadata jsonb,
    title text,
    similarity float
)
LANGUAGE sql STABLE
AS $$
    SELECT
        rag_corpus.id,
        rag_corpus.content,
        rag_corpus.metadata,
        rag_corpus.title,
        1 - (rag_corpus.embedding <=> query_embedding) AS similarity
    FROM rag_corpus
    WHERE 1 - (rag_corpus.embedding <=> query_embedding) > match_threshold
    ORDER BY similarity DESC
    LIMIT match_count;
$$;

DROP FUNCTION IF EXISTS match_medical_documents(vector, float, int);

COMMIT;
