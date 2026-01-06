"""End-to-end tests for ADR 0001 entity system queries.

Tests the PostgreSQL queries defined in docs/adr/0001-static-entity-system.md:
1. resolve_entity() - Inheritance resolution via recursive CTE
2. Fuzzy matching - pg_trgm similarity search for entity names
3. Room instance lookup - Find entities in a room
"""

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
    },
]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def populated_db(test_db):
    """Insert sample entity data into the test database."""
    async with test_db.acquire() as conn:
        # Insert entities in order (prototypes first due to FK constraints)
        for entity in SAMPLE_ENTITIES:
            await conn.execute(
                """
                INSERT INTO entities (
                    id, name, prototype_id, description_short, description_long,
                    on_look, on_touch, on_attack, on_use, on_take,
                    container_id, contents_visible
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
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
            )

        # Create entity instances in a room
        await conn.execute(
            """
            INSERT INTO entity_instances (entity_id, room) VALUES
            ('vase', 'tavern'),
            ('table', 'tavern'),
            ('lamp', 'tavern'),
            ('book', 'tavern')
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
        assert names == {"Fancy Vase", "Wooden Table", "Brass Lamp", "Old Book"}

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
