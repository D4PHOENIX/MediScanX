BEGIN;

-- Float16 vectors cannot cast across dimensions, so we need to truncate and re-seed the corpus.
TRUNCATE TABLE rag_corpus;

DROP INDEX IF EXISTS idx_rag_corpus_embedding;

ALTER TABLE rag_corpus ALTER COLUMN embedding TYPE halfvec(768);

-- Recreate the HNSW index. Note: dropping this index would reclaim ~120 MB if space is needed.
CREATE INDEX IF NOT EXISTS idx_rag_corpus_embedding 
    ON rag_corpus USING hnsw (embedding halfvec_cosine_ops);

-- Drop the old match_rag_corpus function
DROP FUNCTION IF EXISTS match_rag_corpus(halfvec, float, int);

CREATE OR REPLACE FUNCTION match_rag_corpus(
    query_embedding halfvec(768),
    match_threshold float,
    match_count int,
    filter_source text DEFAULT NULL,
    filter_specialty text DEFAULT NULL
) RETURNS TABLE (
    id uuid,
    content text,
    metadata jsonb,
    title text,
    source text,
    external_id text,
    similarity float
)
LANGUAGE sql STABLE
AS $$
    SELECT
        rag_corpus.id,
        rag_corpus.content,
        rag_corpus.metadata,
        rag_corpus.title,
        rag_corpus.source,
        rag_corpus.external_id,
        1 - (rag_corpus.embedding <=> query_embedding) AS similarity
    FROM rag_corpus
    WHERE 1 - (rag_corpus.embedding <=> query_embedding) > match_threshold
      AND (filter_source IS NULL OR source = filter_source)
      AND (filter_specialty IS NULL OR specialty_tag = filter_specialty)
    ORDER BY similarity DESC
    LIMIT match_count;
$$;

COMMIT;
