-- Migration: 009_item_system
-- Description: Item pickup/drop system with tags, rarity, and spawning pools (ADR 0004)

SET lock_timeout = '1s';
SET statement_timeout = '5s';

-- Add on_drop verb action
ALTER TYPE verb_action ADD VALUE 'on_drop';

-- Rarity enum for weighted spawn selection
-- Weights for standard rarities sum to 1000 (excluding none and quest):
-- none=0 (static world items, default), common=600 (60%), uncommon=250 (25%),
-- rare=100 (10%), epic=40 (4%), legendary=9 (0.9%), mythic=1 (0.1%),
-- quest=600 (spawns from dedicated tag-specific pools)
CREATE TYPE rarity AS ENUM ('none', 'common', 'uncommon', 'rare', 'epic', 'legendary', 'mythic', 'quest');

-- Entity tags for categorization (many-to-many)
-- Space-separated in .rec files: Tags: beverage alcoholic
CREATE TABLE entity_tags (
    entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY (entity_id, tag)
);
CREATE INDEX idx_entity_tags_tag ON entity_tags(tag);

-- Spawning pools for respawning items in the world
-- Note: Using INTEGER for counts is intentional - we'll never need > 2B items in a pool
CREATE TABLE spawning_pools (
    id TEXT PRIMARY KEY,
    room TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    container_id TEXT REFERENCES entities(id) ON DELETE CASCADE,
    tag_query TEXT NOT NULL,
    -- squawk-ignore prefer-bigint-over-int
    max_count INTEGER NOT NULL DEFAULT 1,
    -- squawk-ignore prefer-bigint-over-int
    respawn_interval_minutes INTEGER NOT NULL DEFAULT 30,
    last_spawn_at TIMESTAMPTZ
);

-- Add rarity and on_drop handler to entities
ALTER TABLE entities ADD COLUMN rarity rarity NOT NULL DEFAULT 'none';
ALTER TABLE entities ADD COLUMN on_drop TEXT;

-- Add spawning pool tracking and player-dropped flag to entity_instances
-- Note: Adding columns without NOT VALID because entity_instances is small
-- squawk-ignore adding-foreign-key-constraint
ALTER TABLE entity_instances ADD COLUMN spawning_pool_id TEXT REFERENCES spawning_pools(id) ON DELETE SET NULL;
ALTER TABLE entity_instances ADD COLUMN player_dropped BOOLEAN NOT NULL DEFAULT FALSE;

-- Index for spawning pool instance queries
-- Note: Using non-concurrent index because we can tolerate brief locks during migration
-- squawk-ignore require-concurrent-index-creation
CREATE INDEX idx_entity_instances_spawning_pool ON entity_instances(spawning_pool_id) WHERE spawning_pool_id IS NOT NULL;

-- Index for floor clutter queries (count player-dropped items per room)
-- squawk-ignore require-concurrent-index-creation
CREATE INDEX idx_entity_instances_player_dropped ON entity_instances(room, player_dropped) WHERE room IS NOT NULL AND player_dropped = TRUE;

-- Add container_entity_id to entity_instances for containment relationships
-- Container is now tracked at instance level (not entity level) so different instances
-- of the same entity can be in different containers
-- squawk-ignore adding-foreign-key-constraint
ALTER TABLE entity_instances ADD COLUMN container_entity_id TEXT REFERENCES entities(id) ON DELETE SET NULL;

-- Index for container contents queries
-- squawk-ignore require-concurrent-index-creation
CREATE INDEX idx_entity_instances_container ON entity_instances(room, container_entity_id) WHERE container_entity_id IS NOT NULL;

-- Drop container_id from entities table (containment now tracked on instances)
-- This also drops the CHECK constraint automatically
-- squawk-ignore ban-drop-column
ALTER TABLE entities DROP COLUMN IF EXISTS container_id;

-- Update resolve_entity() to include rarity and on_drop in inheritance chain
DROP FUNCTION IF EXISTS resolve_entity(TEXT);

CREATE FUNCTION resolve_entity(target_id TEXT)
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
    on_open TEXT,
    on_close TEXT,
    on_drop TEXT,
    contents_visible BOOLEAN,
    focus_mode focus_mode,
    spawn_mode spawn_mode,
    rarity rarity
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
        e.on_open,
        e.on_close,
        e.on_drop,
        e.contents_visible,
        e.focus_mode,
        e.spawn_mode,
        e.rarity,
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
        e.on_open,
        e.on_close,
        e.on_drop,
        e.contents_visible,
        e.focus_mode,
        e.spawn_mode,
        e.rarity,
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
    (SELECT ic.on_open FROM inheritance_chain ic WHERE ic.on_open IS NOT NULL ORDER BY ic.depth LIMIT 1),
    (SELECT ic.on_close FROM inheritance_chain ic WHERE ic.on_close IS NOT NULL ORDER BY ic.depth LIMIT 1),
    (SELECT ic.on_drop FROM inheritance_chain ic WHERE ic.on_drop IS NOT NULL ORDER BY ic.depth LIMIT 1),
    (SELECT ic.contents_visible FROM inheritance_chain ic WHERE ic.contents_visible IS NOT NULL ORDER BY ic.depth LIMIT 1),
    -- focus_mode: NULL = inherit from prototype, find first non-NULL; default to 'none' if all NULL
    COALESCE(
        (SELECT ic.focus_mode FROM inheritance_chain ic WHERE ic.focus_mode IS NOT NULL ORDER BY ic.depth LIMIT 1),
        'none'::focus_mode
    ),
    -- spawn_mode is NOT NULL so first in chain always wins (the entity itself)
    (SELECT ic.spawn_mode FROM inheritance_chain ic ORDER BY ic.depth LIMIT 1),
    -- rarity is NOT NULL so first in chain always wins (the entity itself)
    (SELECT ic.rarity FROM inheritance_chain ic ORDER BY ic.depth LIMIT 1);
$$ LANGUAGE sql STABLE;
