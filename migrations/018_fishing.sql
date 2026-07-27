-- Migration: 018_fishing
-- Description: Add on_fish verb action and entity handler for fishing mechanic

SET lock_timeout = '1s';
SET statement_timeout = '5s';

-- Add on_fish verb action
-- squawk-ignore require-enum-value-ordering
ALTER TYPE verb_action ADD VALUE 'on_fish';

-- Add on_fish handler column to entities
ALTER TABLE entities ADD COLUMN on_fish TEXT;

-- Update resolve_entity() to include on_fish in inheritance chain
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
    on_fish TEXT,
    contents_visible BOOLEAN,
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
        e.on_fish,
        e.contents_visible,
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
        e.on_fish,
        e.contents_visible,
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
    (SELECT ic.on_fish FROM inheritance_chain ic WHERE ic.on_fish IS NOT NULL ORDER BY ic.depth LIMIT 1),
    (SELECT ic.contents_visible FROM inheritance_chain ic WHERE ic.contents_visible IS NOT NULL ORDER BY ic.depth LIMIT 1),
    -- rarity is NOT NULL so first in chain always wins (the entity itself)
    (SELECT ic.rarity FROM inheritance_chain ic ORDER BY ic.depth LIMIT 1);
$$ LANGUAGE sql STABLE;
