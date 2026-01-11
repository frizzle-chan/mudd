"""End-to-end tests for entity system queries.

Tests the PostgreSQL queries defined in docs/adr/0001-static-entity-system.md:
1. resolve_entity() - Inheritance resolution via recursive CTE
2. Fuzzy matching - pg_trgm similarity search for entity names
3. Room instance lookup - Find entities in a room

Tests the inventory system from docs/adr/0002-inventory-system.md:
4. Mutual exclusivity constraint - room XOR owner_id
5. Spawn mode - none/move/clone behavior
6. Owner cascade delete
"""

import asyncpg
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="module")


# Sample entity data matching the inheritance structure from data/entities.rec
SAMPLE_ENTITIES = [
    # Base prototype - all entities inherit from this
    {
        "id": "object",
        "name": "object",
        "prototype_id": None,
        "description_short": "a {name}",
        "description_long": None,
        "on_look": "You see nothing special about the {name}.",
        "on_touch": "You touch the {name}. Nothing happens.",
        "on_attack": "You attack the {name}, but it has no effect.",
        "on_use": "You can't use the {name}.",
        "on_take": "You can't take the {name}.",
        "container_id": None,
        "contents_visible": None,
    },
    # Glass object prototype - overrides on_attack
    {
        "id": "glass_object",
        "name": "Glass Object",
        "prototype_id": "object",
        "description_short": None,
        "description_long": None,
        "on_look": None,
        "on_touch": None,
        "on_attack": "You suppress the intrusive thought to smash the {name}",
        "on_use": None,
        "on_take": None,
        "container_id": None,
        "contents_visible": None,
    },
    # Furniture prototype
    {
        "id": "furniture",
        "name": "furniture",
        "prototype_id": "object",
        "description_short": "a {name} sits here",
        "description_long": None,
        "on_look": None,
        "on_touch": None,
        "on_attack": None,
        "on_use": None,
        "on_take": None,
        "container_id": None,
        "contents_visible": None,
    },
    # Concrete entity: vase (inherits from glass_object)
    {
        "id": "vase",
        "name": "Fancy Vase",
        "prototype_id": "glass_object",
        "description_short": "a teal {name} with yellow roses",
        "description_long": "A teal ceramic vase with gold trim.",
        "on_look": None,
        "on_touch": None,
        "on_attack": None,
        "on_use": None,
        "on_take": None,
        "container_id": None,
        "contents_visible": None,
    },
    # Concrete entity: table (furniture with visible contents)
    {
        "id": "table",
        "name": "Wooden Table",
        "prototype_id": "furniture",
        "description_short": "a {name} sits in the corner",
        "description_long": "A sturdy oak table with worn edges.",
        "on_look": None,
        "on_touch": None,
        "on_attack": None,
        "on_use": None,
        "on_take": None,
        "container_id": None,
        "contents_visible": True,
    },
    # Concrete entity: lamp (contained in table)
    {
        "id": "lamp",
        "name": "Brass Lamp",
        "prototype_id": "object",
        "description_short": "a {name}",
        "description_long": "A polished brass lamp with a green shade.",
        "on_look": None,
        "on_touch": None,
        "on_attack": None,
        "on_use": "You turn on the {name}. Light fills the room.",
        "on_take": None,
        "container_id": "table",
        "contents_visible": None,
    },
    # Concrete entity: book (contained in table)
    {
        "id": "book",
        "name": "Old Book",
        "prototype_id": "object",
        "description_short": "an {name}",
        "description_long": "A leather-bound tome with yellowed pages.",
        "on_look": "The book is titled 'A History of the Realm'.",
        "on_touch": None,
        "on_attack": None,
        "on_use": None,
        "on_take": None,
        "container_id": "table",
        "contents_visible": None,
        "spawn_mode": "none",
    },
    # Takeable item with move spawn mode
    {
        "id": "coin",
        "name": "Gold Coin",
        "prototype_id": "object",
        "description_short": "a shiny {name}",
        "description_long": "A gold coin with the king's face on it.",
        "on_look": None,
        "on_touch": None,
        "on_attack": None,
        "on_use": None,
        "on_take": "You pick up the {name}.",
        "container_id": None,
        "contents_visible": None,
        "spawn_mode": "move",
    },
    # Infinite source with clone spawn mode
    {
        "id": "scroll",
        "name": "Magic Scroll",
        "prototype_id": "object",
        "description_short": "a {name}",
        "description_long": "A scroll that produces infinite copies.",
        "on_look": None,
        "on_touch": None,
        "on_attack": None,
        "on_use": None,
        "on_take": "You take a copy of the {name}.",
        "container_id": None,
        "contents_visible": None,
        "spawn_mode": "clone",
    },
]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def populated_db(test_db):
    """Insert sample entity data into the test database."""
    async with test_db.acquire() as conn:
        # Insert entities in order (prototypes first due to FK constraints)
        for entity in SAMPLE_ENTITIES:
            spawn_mode = entity.get("spawn_mode", "none")
            await conn.execute(
                """
                INSERT INTO entities (
                    id, name, prototype_id, description_short, description_long,
                    on_look, on_touch, on_attack, on_use, on_take,
                    container_id, contents_visible, spawn_mode
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                """,
                entity["id"],
                entity["name"],
                entity["prototype_id"],
                entity["description_short"],
                entity["description_long"],
                entity["on_look"],
                entity["on_touch"],
                entity["on_attack"],
                entity["on_use"],
                entity["on_take"],
                entity["container_id"],
                entity["contents_visible"],
                spawn_mode,
            )

        # Create zone and room for FK constraints
        await conn.execute(
            """
            INSERT INTO zones (id, name) VALUES ('test-zone', 'Test Zone')
            ON CONFLICT (id) DO NOTHING
            """
        )
        await conn.execute(
            """
            INSERT INTO rooms (id, name, description, zone_id)
            VALUES ('tavern', 'Tavern', 'A test tavern', 'test-zone')
            ON CONFLICT (id) DO NOTHING
            """
        )

        # Create entity instances in a room
        await conn.execute(
            """
            INSERT INTO entity_instances (entity_id, room) VALUES
            ('vase', 'tavern'),
            ('table', 'tavern'),
            ('lamp', 'tavern'),
            ('book', 'tavern'),
            ('coin', 'tavern'),
            ('scroll', 'tavern')
            """
        )

        # Create a test user for inventory tests
        await conn.execute(
            """
            INSERT INTO users (id, current_room) VALUES (12345, 'tavern')
            """
        )

    yield test_db


class TestResolveEntity:
    """Test the resolve_entity() function for inheritance resolution."""

    async def test_resolves_direct_property(self, populated_db):
        """Entity's own properties are returned directly."""
        async with populated_db.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM resolve_entity('vase')")

        assert row["id"] == "vase"
        assert row["name"] == "Fancy Vase"
        assert row["description_short"] == "a teal {name} with yellow roses"
        assert row["description_long"] == "A teal ceramic vase with gold trim."

    async def test_inherits_from_parent(self, populated_db):
        """Properties not defined on entity are inherited from prototype."""
        async with populated_db.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM resolve_entity('vase')")

        # on_attack should come from glass_object (parent)
        expected = "You suppress the intrusive thought to smash the {name}"
        assert row["on_attack"] == expected

    async def test_inherits_from_grandparent(self, populated_db):
        """Properties walk up the prototype chain to grandparent."""
        async with populated_db.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM resolve_entity('vase')")

        # on_touch should come from object (grandparent via glass_object)
        assert row["on_touch"] == "You touch the {name}. Nothing happens."
        assert row["on_take"] == "You can't take the {name}."

    async def test_child_overrides_parent(self, populated_db):
        """Child properties override parent properties."""
        async with populated_db.acquire() as conn:
            # glass_object overrides on_attack from object
            row = await conn.fetchrow("SELECT * FROM resolve_entity('glass_object')")

        expected = "You suppress the intrusive thought to smash the {name}"
        assert row["on_attack"] == expected
        # But still inherits on_touch from object
        assert row["on_touch"] == "You touch the {name}. Nothing happens."

    async def test_resolves_contents_visible(self, populated_db):
        """contents_visible is resolved through inheritance."""
        async with populated_db.acquire() as conn:
            # table has contents_visible = True
            row = await conn.fetchrow("SELECT * FROM resolve_entity('table')")
            assert row["contents_visible"] is True

            # lamp inherits from object which has no contents_visible
            row = await conn.fetchrow("SELECT * FROM resolve_entity('lamp')")
            assert row["contents_visible"] is None


class TestFuzzyMatching:
    """Test the pg_trgm fuzzy matching query from the ADR."""

    async def test_fuzzy_match_partial_name(self, populated_db):
        """Fuzzy match finds entities with partial name matches."""
        async with populated_db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT r.*, ei.id AS instance_id, similarity(r.name, $1) AS match_score
                FROM entity_instances ei
                CROSS JOIN LATERAL resolve_entity(ei.entity_id) r
                WHERE ei.room = $2
                  AND r.name % $1
                ORDER BY match_score DESC
                """,
                "Vase",
                "tavern",
            )

        assert len(rows) >= 1
        assert rows[0]["name"] == "Fancy Vase"
        assert rows[0]["match_score"] > 0.3

    async def test_fuzzy_match_book(self, populated_db):
        """Fuzzy match finds book with partial match."""
        async with populated_db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT r.*, ei.id AS instance_id, similarity(r.name, $1) AS match_score
                FROM entity_instances ei
                CROSS JOIN LATERAL resolve_entity(ei.entity_id) r
                WHERE ei.room = $2
                  AND r.name % $1
                ORDER BY match_score DESC
                """,
                "book",
                "tavern",
            )

        assert len(rows) >= 1
        assert rows[0]["name"] == "Old Book"

    async def test_fuzzy_match_returns_resolved_properties(self, populated_db):
        """Fuzzy match results include inherited properties."""
        async with populated_db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT r.*, ei.id AS instance_id, similarity(r.name, $1) AS match_score
                FROM entity_instances ei
                CROSS JOIN LATERAL resolve_entity(ei.entity_id) r
                WHERE ei.room = $2
                  AND r.name % $1
                ORDER BY match_score DESC
                """,
                "lamp",
                "tavern",
            )

        assert len(rows) >= 1
        lamp = rows[0]
        assert lamp["name"] == "Brass Lamp"
        # on_use is defined on lamp directly
        assert lamp["on_use"] == "You turn on the {name}. Light fills the room."
        # on_touch is inherited from object
        assert lamp["on_touch"] == "You touch the {name}. Nothing happens."


class TestRoomLookup:
    """Test basic room instance lookups."""

    async def test_find_all_entities_in_room(self, populated_db):
        """Find all entity instances in a room."""
        async with populated_db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT ei.*, e.name
                FROM entity_instances ei
                JOIN entities e ON e.id = ei.entity_id
                WHERE ei.room = $1
                """,
                "tavern",
            )

        names = {row["name"] for row in rows}
        assert names == {
            "Fancy Vase",
            "Wooden Table",
            "Brass Lamp",
            "Old Book",
            "Gold Coin",
            "Magic Scroll",
        }

    async def test_empty_room_returns_no_results(self, populated_db):
        """Query on empty room returns no results."""
        async with populated_db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT ei.*, e.name
                FROM entity_instances ei
                JOIN entities e ON e.id = ei.entity_id
                WHERE ei.room = $1
                """,
                "nonexistent_room",
            )

        assert len(rows) == 0


class TestContainment:
    """Test entity containment relationships."""

    async def test_contained_entities_have_container_id(self, populated_db):
        """Entities with container_id are properly linked."""
        async with populated_db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT e.id, e.name, e.container_id, c.name AS container_name
                FROM entities e
                JOIN entities c ON c.id = e.container_id
                WHERE e.container_id IS NOT NULL
                """
            )

        contained = {row["id"]: row["container_name"] for row in rows}
        assert contained["lamp"] == "Wooden Table"
        assert contained["book"] == "Wooden Table"

    async def test_top_level_entities_have_no_container(self, populated_db):
        """Top-level entities have NULL container_id."""
        async with populated_db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, name FROM entities
                WHERE container_id IS NULL
                  AND id IN ('vase', 'table', 'object', 'furniture', 'glass_object')
                """
            )

        ids = {row["id"] for row in rows}
        assert "vase" in ids
        assert "table" in ids


class TestInventory:
    """Test inventory system from ADR 0002."""

    async def test_mutual_exclusivity_both_set_fails(self, populated_db):
        """Cannot set both room and owner_id."""
        async with populated_db.acquire() as conn:
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    """
                    INSERT INTO entity_instances (entity_id, room, owner_id)
                    VALUES ('coin', 'tavern', 12345)
                    """
                )

    async def test_mutual_exclusivity_neither_set_fails(self, populated_db):
        """Cannot have both room and owner_id NULL."""
        async with populated_db.acquire() as conn:
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    """
                    INSERT INTO entity_instances (entity_id, room, owner_id)
                    VALUES ('coin', NULL, NULL)
                    """
                )

    async def test_instance_in_room(self, populated_db):
        """Instance with room set and owner_id NULL is valid."""
        async with populated_db.acquire() as conn:
            # This should work - instance in room
            result = await conn.fetchrow(
                """
                SELECT id, room, owner_id FROM entity_instances
                WHERE entity_id = 'coin' AND room = 'tavern'
                """
            )
        assert result is not None
        assert result["room"] == "tavern"
        assert result["owner_id"] is None

    async def test_instance_in_inventory(self, populated_db):
        """Instance with owner_id set and room NULL is valid."""
        async with populated_db.acquire() as conn:
            # Insert an item in inventory
            await conn.execute(
                """
                INSERT INTO entity_instances (entity_id, room, owner_id)
                VALUES ('coin', NULL, 12345)
                """
            )
            result = await conn.fetchrow(
                """
                SELECT id, room, owner_id FROM entity_instances
                WHERE entity_id = 'coin' AND owner_id = 12345
                """
            )
        assert result is not None
        assert result["room"] is None
        assert result["owner_id"] == 12345

    async def test_owner_cascade_delete(self, populated_db):
        """Deleting user cascades to their inventory items."""
        async with populated_db.acquire() as conn:
            # Create a new user with an inventory item
            await conn.execute(
                "INSERT INTO users (id, current_room) VALUES (99999, 'tavern')"
            )
            await conn.execute(
                """
                INSERT INTO entity_instances (entity_id, room, owner_id)
                VALUES ('scroll', NULL, 99999)
                """
            )
            # Verify item exists
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM entity_instances WHERE owner_id = 99999"
            )
            assert count == 1

            # Delete user
            await conn.execute("DELETE FROM users WHERE id = 99999")

            # Verify item was cascade deleted
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM entity_instances WHERE owner_id = 99999"
            )
            assert count == 0


class TestSpawnMode:
    """Test spawn_mode field and resolve_entity() inclusion."""

    async def test_resolve_entity_includes_spawn_mode(self, populated_db):
        """resolve_entity() returns spawn_mode."""
        async with populated_db.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM resolve_entity('coin')")

        assert row["spawn_mode"] == "move"

    async def test_spawn_mode_none(self, populated_db):
        """Static entities have spawn_mode='none'."""
        async with populated_db.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM resolve_entity('vase')")

        assert row["spawn_mode"] == "none"

    async def test_spawn_mode_clone(self, populated_db):
        """Infinite source entities have spawn_mode='clone'."""
        async with populated_db.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM resolve_entity('scroll')")

        assert row["spawn_mode"] == "clone"

    async def test_spawn_mode_default(self, populated_db):
        """Entities without explicit spawn_mode default to 'none'."""
        async with populated_db.acquire() as conn:
            # 'object' prototype has no explicit spawn_mode
            row = await conn.fetchrow("SELECT * FROM resolve_entity('object')")

        assert row["spawn_mode"] == "none"
