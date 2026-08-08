-- database/migrations/add_sync_metadata.sql
-- Non-destructive: safe to run against a live database.
-- Adds the sync tracking table used by the POST /api/sync endpoint.

CREATE TABLE IF NOT EXISTS sync_metadata (
    id                   SERIAL PRIMARY KEY,
    last_successful_sync TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sync_metadata_ts ON sync_metadata (last_successful_sync DESC);
