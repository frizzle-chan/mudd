-- Migration: 017_remove_focus_mode
-- Description: Remove focus_mode column and enum, update resolve_entity function
-- Focus is now controlled by effects.set_focus() and effects.clear_focus() in templates

SET lock_timeout = '1s';
SET statement_timeout = '5s';

-- Drop focus_mode column from entities table
-- squawk-ignore ban-drop-column
ALTER TABLE entities DROP COLUMN IF EXISTS focus_mode;

-- Update resolve_entity() to remove focus_mode from return type
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
    -- rarity is NOT NULL so first in chain always wins (the entity itself)
    (SELECT ic.rarity FROM inheritance_chain ic ORDER BY ic.depth LIMIT 1);
$$ LANGUAGE sql STABLE;

-- Drop the focus_mode enum type (must be after dropping column)
DROP TYPE IF EXISTS focus_mode;
