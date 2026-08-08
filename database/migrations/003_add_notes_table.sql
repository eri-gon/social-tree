-- 003_add_notes_table.sql
CREATE TABLE IF NOT EXISTS notes (
    id         SERIAL PRIMARY KEY,
    title      TEXT NOT NULL DEFAULT '',
    content    TEXT NOT NULL DEFAULT '',
    color      VARCHAR(32) DEFAULT 'default',
    pinned     BOOLEAN DEFAULT FALSE,
    source     VARCHAR(64) DEFAULT 'manual', -- 'manual' | 'keep_import'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
