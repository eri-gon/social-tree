-- trace_introductions.sql
-- Traces paths of introductions starting from the owner (Eric Gan) up to 3 degrees of separation.

-- Clean up previous trace run to make the script idempotent
DELETE FROM edges WHERE source = 'eric_gan';
DELETE FROM nodes WHERE id = 'eric_gan';

-- 1. Insert the owner node
INSERT INTO nodes (id, name, type, metadata, contexts)
VALUES ('eric_gan', 'Eric Gan', 'person', '["owner"]'::jsonb, '[]'::jsonb)
ON CONFLICT (id) DO NOTHING;

-- 2. Link the owner to all direct contacts (people with no incoming introduction edges from OTHER people)
INSERT INTO edges (source, target, type, context)
SELECT 'eric_gan', id, 'introduction', 'Direct Contact'
FROM nodes
WHERE type = 'person' 
  AND id NOT IN (
      SELECT DISTINCT target 
      FROM edges 
      WHERE type = 'introduction' AND target <> source
  )
  AND id <> 'eric_gan'
ON CONFLICT (source, target, type) DO NOTHING;

-- 3. Run Recursive CTE to trace introductions up to 3 degrees of separation
WITH RECURSIVE intro_path AS (
    -- Anchor: Start with the owner
    SELECT 
        id AS person_id,
        name AS person_name,
        0 AS depth,
        ARRAY[id]::VARCHAR[] AS path
    FROM nodes
    WHERE id = 'eric_gan'
    
    UNION ALL
    
    -- Recursive step: Traverse introduction connections
    SELECT 
        n.id,
        n.name,
        ip.depth + 1,
        ip.path || n.id
    FROM edges e
    JOIN nodes n ON e.target = n.id
    JOIN intro_path ip ON e.source = ip.person_id
    WHERE e.type = 'introduction'
      AND ip.depth < 3                     -- Traverse up to 3 degrees of separation
      AND NOT (n.id = ANY(ip.path))        -- Prevent infinite loops/cycles
)
SELECT 
    person_id,
    person_name,
    depth,
    array_to_string(path, ' -> ') AS introduction_path
FROM intro_path
WHERE depth > 0                           -- Exclude the owner node from the results
ORDER BY depth ASC, person_name ASC;
