-- Migration: 002_entities
-- Description: Entity system with prototypical inheritance and inventory support

-- Enable fuzzy matching for entity name search
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Spawn mode determines what happens when a player takes an entity
-- 'none': Static decoration, cannot be taken
-- 'move': One-time pickup, instance moves to inventory
-- 'clone': Infinite copies, each take creates new instance in inventory
CREATE TYPE spawn_mode AS ENUM ('none', 'move', 'clone');

CREATE TABLE entities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    prototype_id TEXT REFERENCES entities(id),

    -- Descriptions (support {name} template interpolation at render time)
    description_short TEXT,
    description_long TEXT,

    -- Handlers: NULL means "inherit from prototype"
    -- Values are text responses with {name} interpolation support
    on_look TEXT,
    on_touch TEXT,
    on_attack TEXT,
    on_use TEXT,
    on_take TEXT,

    -- Containment (for nested objects like "lamp on table")
    container_id TEXT REFERENCES entities(id),
    contents_visible BOOLEAN,  -- NULL = inherit; TRUE = show children in room; FALSE = show only when examined

    -- Spawn behavior when taken
    spawn_mode spawn_mode NOT NULL DEFAULT 'none',

    -- Constraints
    CHECK (id != prototype_id),  -- No self-inheritance
    CHECK (id != container_id)   -- No self-containment
);

CREATE TABLE entity_instances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id TEXT NOT NULL REFERENCES entities(id),
    room TEXT,  -- Logical room name (NULL when in inventory)
    owner_id BIGINT REFERENCES users(id) ON DELETE CASCADE,  -- Player who owns this (NULL when in room)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Mutual exclusivity: instance is in room XOR in inventory
    CONSTRAINT chk_location_exclusive CHECK (
        (room IS NOT NULL AND owner_id IS NULL)
        OR (room IS NULL AND owner_id IS NOT NULL)
    )
);

-- Indexes
CREATE INDEX idx_entity_instances_room ON entity_instances(room) WHERE room IS NOT NULL;
CREATE INDEX idx_entity_instances_owner ON entity_instances(owner_id) WHERE owner_id IS NOT NULL;
CREATE INDEX idx_entities_name_trgm ON entities USING gin(name gin_trgm_ops);
CREATE INDEX idx_entities_prototype ON entities(prototype_id);

-- Inheritance resolution function
-- Resolves an entity's properties by walking up the prototype chain.
-- Child properties override parent properties (first non-NULL wins).
CREATE OR REPLACE FUNCTION resolve_entity(target_id TEXT)
RETURNS TABLE (
    id TEXT,
    name TEXT,
    description_short TEXT,
    description_long TEXT,
    on_look TEXT,
    on_touch TEXT,
    on_attack TEXT,
    on_use TEXT,
    on_take TEXT,
    contents_visible BOOLEAN,
    spawn_mode spawn_mode
) AS $$
WITH RECURSIVE inheritance_chain AS (
    -- Base case: the entity itself
    SELECT
        e.id,
        e.name,
        e.prototype_id,
        e.description_short,
        e.description_long,
        e.on_look,
        e.on_touch,
        e.on_attack,
        e.on_use,
        e.on_take,
        e.contents_visible,
        e.spawn_mode,
        0 AS depth
    FROM entities e
    WHERE e.id = target_id

    UNION ALL

    -- Recursive case: walk up to prototype
    SELECT
        e.id,
        e.name,
        e.prototype_id,
        e.description_short,
        e.description_long,
        e.on_look,
        e.on_touch,
        e.on_attack,
        e.on_use,
        e.on_take,
        e.contents_visible,
        e.spawn_mode,
        ic.depth + 1
    FROM entities e
    JOIN inheritance_chain ic ON e.id = ic.prototype_id
    WHERE ic.depth < 10  -- Max inheritance depth
)
SELECT
    target_id AS id,
    (SELECT ic.name FROM inheritance_chain ic WHERE ic.name IS NOT NULL ORDER BY ic.depth LIMIT 1),
    (SELECT ic.description_short FROM inheritance_chain ic WHERE ic.description_short IS NOT NULL ORDER BY ic.depth LIMIT 1),
    (SELECT ic.description_long FROM inheritance_chain ic WHERE ic.description_long IS NOT NULL ORDER BY ic.depth LIMIT 1),
    (SELECT ic.on_look FROM inheritance_chain ic WHERE ic.on_look IS NOT NULL ORDER BY ic.depth LIMIT 1),
    (SELECT ic.on_touch FROM inheritance_chain ic WHERE ic.on_touch IS NOT NULL ORDER BY ic.depth LIMIT 1),
    (SELECT ic.on_attack FROM inheritance_chain ic WHERE ic.on_attack IS NOT NULL ORDER BY ic.depth LIMIT 1),
    (SELECT ic.on_use FROM inheritance_chain ic WHERE ic.on_use IS NOT NULL ORDER BY ic.depth LIMIT 1),
    (SELECT ic.on_take FROM inheritance_chain ic WHERE ic.on_take IS NOT NULL ORDER BY ic.depth LIMIT 1),
    (SELECT ic.contents_visible FROM inheritance_chain ic WHERE ic.contents_visible IS NOT NULL ORDER BY ic.depth LIMIT 1),
    -- spawn_mode is NOT NULL so first in chain always wins (the entity itself)
    (SELECT ic.spawn_mode FROM inheritance_chain ic ORDER BY ic.depth LIMIT 1);
$$ LANGUAGE sql STABLE;
