-- schema.sql
-- Adjacency List model for personal CRM social graph

-- Drop tables if they exist to start fresh
DROP TABLE IF EXISTS edges CASCADE;
DROP TABLE IF EXISTS nodes CASCADE;

-- Table for unique nodes (people and group contexts)
CREATE TABLE nodes (
    id VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    type VARCHAR(50) NOT NULL, -- 'person' or 'group'
    metadata JSONB DEFAULT '[]'::jsonb, -- Array of metadata tags
    contexts JSONB DEFAULT '[]'::jsonb -- Array of group contexts where they were encountered
);

-- Table for directional relationship connections
CREATE TABLE edges (
    id SERIAL PRIMARY KEY,
    source VARCHAR(255) NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    target VARCHAR(255) NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    type VARCHAR(50) NOT NULL, -- 'introduction' or 'membership'
    context VARCHAR(255), -- The context or group name associated with this connection
    CONSTRAINT unique_edge UNIQUE (source, target, type)
);

-- Create indexes for performance on foreign keys and search paths
CREATE INDEX idx_nodes_type ON nodes(type);
CREATE INDEX idx_edges_source ON edges(source);
CREATE INDEX idx_edges_target ON edges(target);
CREATE INDEX idx_edges_type ON edges(type);
