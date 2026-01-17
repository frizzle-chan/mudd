-- Migration: 006_user_focus
-- Description: User focus context for modal interactions (ADR 0003)

SET lock_timeout = '1s';
SET statement_timeout = '5s';

-- Focus mode enum for determining which entities establish focus on open
CREATE TYPE focus_mode AS ENUM ('none', 'container');
-- Future: 'document', 'terminal', 'conversation'

-- Add open/close handlers and focus mode to entities table
ALTER TABLE entities ADD COLUMN on_open TEXT;
ALTER TABLE entities ADD COLUMN on_close TEXT;
-- focus_mode: NULL = inherit from prototype, 'none' = explicitly no focus, 'container' = container focus
ALTER TABLE entities ADD COLUMN focus_mode focus_mode DEFAULT NULL;

-- Add new verb actions
ALTER TYPE verb_action ADD VALUE 'on_open';
ALTER TYPE verb_action ADD VALUE 'on_close';

-- User focus table: tracks which entity each user has "open"
CREATE TABLE user_focus (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    room TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for timeout queries (lazy cleanup checks updated_at)
CREATE INDEX idx_user_focus_updated ON user_focus(updated_at);

-- Update resolve_entity() to include new fields in inheritance chain
-- Drop and recreate to update return signature
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
    contents_visible BOOLEAN,
    focus_mode focus_mode,
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
        e.on_open,
        e.on_close,
        e.contents_visible,
        e.focus_mode,
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
        e.on_open,
        e.on_close,
        e.contents_visible,
        e.focus_mode,
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
    (SELECT ic.on_open FROM inheritance_chain ic WHERE ic.on_open IS NOT NULL ORDER BY ic.depth LIMIT 1),
    (SELECT ic.on_close FROM inheritance_chain ic WHERE ic.on_close IS NOT NULL ORDER BY ic.depth LIMIT 1),
    (SELECT ic.contents_visible FROM inheritance_chain ic WHERE ic.contents_visible IS NOT NULL ORDER BY ic.depth LIMIT 1),
    -- focus_mode: NULL = inherit from prototype, find first non-NULL; default to 'none' if all NULL
    COALESCE(
        (SELECT ic.focus_mode FROM inheritance_chain ic WHERE ic.focus_mode IS NOT NULL ORDER BY ic.depth LIMIT 1),
        'none'::focus_mode
    ),
    -- spawn_mode is NOT NULL so first in chain always wins (the entity itself)
    (SELECT ic.spawn_mode FROM inheritance_chain ic ORDER BY ic.depth LIMIT 1);
$$ LANGUAGE sql STABLE;
