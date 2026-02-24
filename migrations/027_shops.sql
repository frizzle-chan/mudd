-- Migration: 027_shops
-- Description: Shop and shop stock tables for the merchant shop system (ADR 0008)

SET lock_timeout = '1s';
SET statement_timeout = '5s';

CREATE TABLE shops (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    preferred_tag TEXT,
    sell_spread REAL NOT NULL DEFAULT 0.5,
    restock_tag TEXT,
    -- squawk-ignore prefer-bigint-over-int
    restock_interval_minutes INT NOT NULL DEFAULT 1440,
    last_restock_at TIMESTAMPTZ
);

CREATE TABLE shop_stock (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shop_id TEXT NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
    entity_instance_id UUID NOT NULL REFERENCES entity_instances(id) ON DELETE CASCADE,
    stocked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_shop_stock_shop ON shop_stock(shop_id);

-- squawk-ignore constraint-missing-not-valid,disallowed-unique-constraint
ALTER TABLE shop_stock ADD CONSTRAINT shop_stock_entity_instance_unique UNIQUE (entity_instance_id);

-- Relax entity_instances location constraint to allow a third state:
-- room=NULL + owner_id=NULL for shop stock items (tracked via shop_stock table)
ALTER TABLE entity_instances DROP CONSTRAINT chk_location_exclusive;

ALTER TABLE entity_instances ADD CONSTRAINT chk_location_exclusive CHECK (
    (room IS NOT NULL AND owner_id IS NULL)
    OR (room IS NULL AND owner_id IS NOT NULL)
    OR (room IS NULL AND owner_id IS NULL)
) NOT VALID;
