-- =============================================================================
-- Migration: 0003_langchain_chat_histories_add_created_at.sql
-- Description: Add missing created_at column to langchain_chat_histories. PowerSync requires this column for offline sync ordering.
-- =============================================================================

ALTER TABLE langchain_chat_histories
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- Back-fill any existing rows that now have the column but no value.
-- DEFAULT now() already handles future inserts; this covers historic rows.
UPDATE langchain_chat_histories
SET created_at = now()
WHERE created_at IS NULL;

-- Optional: index for efficient time-range queries by PowerSync.
CREATE INDEX IF NOT EXISTS idx_langchain_chat_histories_created_at
    ON langchain_chat_histories (created_at);
