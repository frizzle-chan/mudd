"""Tests for entity loader.

Tests:
1. load_entities_from_rec parses entities from world rec files
2. Entity fields are correctly parsed
3. Validation detects invalid prototype references
4. Validation detects circular prototype inheritance
5. Validation detects circular containment
6. Topological sort orders prototypes before children
7. sync_entities loads entities to database
8. Re-sync removes entities not in files
"""

import pytest
import pytest_asyncio

from mudd.services.entity_loader import _validate_and_sort_entities, sync_entities
from mudd.services.zone_loader import (
    Entity,
    load_entities_from_rec,
    load_rooms_from_rec,
)


class TestLoadEntitiesFromRec:
    """Test parsing entities from rec files."""

    def test_loads_entities(self):
        """Entities are parsed from mansion.rec."""
        entities = load_entities_from_rec()
        assert len(entities) > 0

    def test_entity_has_required_fields(self):
        """Each entity has id and name."""
        entities = load_entities_from_rec()
        for entity in entities:
            assert entity.id, f"Entity must have id: {entity}"
            assert entity.name, f"Entity must have name: {entity}"

    def test_base_object_entity_exists(self):
        """The base 'object' prototype from mansion.rec is loaded."""
        entities = load_entities_from_rec()
        entity_ids = {e.id for e in entities}
        assert "object" in entity_ids

    def test_foyer_table_entity_exists(self):
        """The foyer_table instance from mansion.rec is loaded."""
        entities = load_entities_from_rec()
        entity_ids = {e.id for e in entities}
        assert "foyer_table" in entity_ids

    def test_prototype_reference_parsed(self):
        """Prototype field is correctly parsed."""
        entities = load_entities_from_rec()
        foyer_table = next((e for e in entities if e.id == "foyer_table"), None)
        assert foyer_table is not None
        assert foyer_table.prototype_id == "furniture"

    def test_container_reference_parsed(self):
        """Container field is correctly parsed."""
        entities = load_entities_from_rec()
        foyer_flower_vase = next(
            (e for e in entities if e.id == "foyer_flower_vase"), None
        )
        assert foyer_flower_vase is not None
        assert foyer_flower_vase.container_id == "foyer_table"

    def test_room_reference_parsed(self):
        """Room field is correctly parsed."""
        entities = load_entities_from_rec()
        foyer_table = next((e for e in entities if e.id == "foyer_table"), None)
        assert foyer_table is not None
        assert foyer_table.room == "foyer"

    def test_contents_visible_parsed(self):
        """ContentsVisible field is correctly parsed as boolean."""
        entities = load_entities_from_rec()
        foyer_table = next((e for e in entities if e.id == "foyer_table"), None)
        assert foyer_table is not None
        assert foyer_table.contents_visible is True

    def test_prototype_has_no_room(self):
        """Prototypes (base entities) have no room field."""
        entities = load_entities_from_rec()
        obj = next((e for e in entities if e.id == "object"), None)
        assert obj is not None
        assert obj.room is None

    def test_spawn_mode_defaults_to_none(self):
        """spawn_mode defaults to 'none' when not specified."""
        entities = load_entities_from_rec()
        foyer_table = next((e for e in entities if e.id == "foyer_table"), None)
        assert foyer_table is not None
        assert foyer_table.spawn_mode == "none"


class TestValidateEntities:
    """Test entity validation logic."""

    def test_valid_entities_pass_validation(self):
        """Valid entity set passes validation."""
        entities = load_entities_from_rec()
        rooms = load_rooms_from_rec()
        room_ids = {r.id for r in rooms}

        # Should not raise
        sorted_entities = _validate_and_sort_entities(entities, room_ids)
        assert len(sorted_entities) == len(entities)

    def test_invalid_prototype_reference_raises(self):
        """Invalid prototype reference raises ValueError."""
        entities = [
            Entity(id="child", name="Child", prototype_id="nonexistent"),
        ]
        with pytest.raises(ValueError, match="invalid prototype 'nonexistent'"):
            _validate_and_sort_entities(entities, set())

    def test_invalid_container_reference_raises(self):
        """Invalid container reference raises ValueError."""
        entities = [
            Entity(id="item", name="Item", container_id="nonexistent"),
        ]
        with pytest.raises(ValueError, match="invalid container 'nonexistent'"):
            _validate_and_sort_entities(entities, set())

    def test_invalid_room_reference_raises(self):
        """Invalid room reference raises ValueError."""
        entities = [
            Entity(id="item", name="Item", room="nonexistent"),
        ]
        with pytest.raises(ValueError, match="invalid room 'nonexistent'"):
            _validate_and_sort_entities(entities, set())

    def test_circular_prototype_inheritance_raises(self):
        """Circular prototype chain raises ValueError."""
        entities = [
            Entity(id="a", name="A", prototype_id="b"),
            Entity(id="b", name="B", prototype_id="a"),
        ]
        with pytest.raises(ValueError, match="Circular prototype inheritance"):
            _validate_and_sort_entities(entities, set())

    def test_self_prototype_raises(self):
        """Self-referencing prototype raises ValueError."""
        entities = [
            Entity(id="a", name="A", prototype_id="a"),
        ]
        with pytest.raises(ValueError, match="Circular prototype inheritance"):
            _validate_and_sort_entities(entities, set())

    def test_circular_containment_raises(self):
        """Circular containment chain raises ValueError."""
        entities = [
            Entity(id="a", name="A", container_id="b"),
            Entity(id="b", name="B", container_id="a"),
        ]
        with pytest.raises(ValueError, match="Circular containment"):
            _validate_and_sort_entities(entities, set())

    def test_self_containment_raises(self):
        """Self-referencing container raises ValueError."""
        entities = [
            Entity(id="a", name="A", container_id="a"),
        ]
        with pytest.raises(ValueError, match="Circular containment"):
            _validate_and_sort_entities(entities, set())

    def test_three_node_prototype_cycle_raises(self):
        """Three-node prototype cycle raises ValueError."""
        entities = [
            Entity(id="a", name="A", prototype_id="b"),
            Entity(id="b", name="B", prototype_id="c"),
            Entity(id="c", name="C", prototype_id="a"),
        ]
        with pytest.raises(ValueError, match="Circular prototype inheritance"):
            _validate_and_sort_entities(entities, set())

    def test_three_node_containment_cycle_raises(self):
        """Three-node containment cycle raises ValueError."""
        entities = [
            Entity(id="a", name="A", container_id="b"),
            Entity(id="b", name="B", container_id="c"),
            Entity(id="c", name="C", container_id="a"),
        ]
        with pytest.raises(ValueError, match="Circular containment"):
            _validate_and_sort_entities(entities, set())


class TestTopologicalSort:
    """Test topological sorting of entities."""

    def test_prototypes_sorted_before_children(self):
        """Prototypes appear before entities that depend on them."""
        entities = [
            Entity(id="child", name="Child", prototype_id="parent"),
            Entity(id="parent", name="Parent"),
        ]
        sorted_entities = _validate_and_sort_entities(entities, set())

        parent_idx = next(i for i, e in enumerate(sorted_entities) if e.id == "parent")
        child_idx = next(i for i, e in enumerate(sorted_entities) if e.id == "child")
        assert parent_idx < child_idx

    def test_deep_inheritance_chain_sorted(self):
        """Deep inheritance chains are sorted correctly."""
        entities = [
            Entity(id="c", name="C", prototype_id="b"),
            Entity(id="a", name="A"),
            Entity(id="b", name="B", prototype_id="a"),
        ]
        sorted_entities = _validate_and_sort_entities(entities, set())

        a_idx = next(i for i, e in enumerate(sorted_entities) if e.id == "a")
        b_idx = next(i for i, e in enumerate(sorted_entities) if e.id == "b")
        c_idx = next(i for i, e in enumerate(sorted_entities) if e.id == "c")
        assert a_idx < b_idx < c_idx

    def test_no_prototype_entities_first(self):
        """Entities without prototypes can appear in any order at the start."""
        entities = [
            Entity(id="child", name="Child", prototype_id="parent"),
            Entity(id="standalone", name="Standalone"),
            Entity(id="parent", name="Parent"),
        ]
        sorted_entities = _validate_and_sort_entities(entities, set())

        child_idx = next(i for i, e in enumerate(sorted_entities) if e.id == "child")
        parent_idx = next(i for i, e in enumerate(sorted_entities) if e.id == "parent")

        # Parent must come before child
        assert parent_idx < child_idx

    def test_containers_sorted_before_contents(self):
        """Containers appear before entities that reference them."""
        entities = [
            Entity(id="item", name="Item", container_id="box"),
            Entity(id="box", name="Box"),
        ]
        sorted_entities = _validate_and_sort_entities(entities, set())

        box_idx = next(i for i, e in enumerate(sorted_entities) if e.id == "box")
        item_idx = next(i for i, e in enumerate(sorted_entities) if e.id == "item")
        assert box_idx < item_idx

    def test_entity_with_both_prototype_and_container_sorted_correctly(self):
        """Entity with both prototype and container is sorted after both."""
        entities = [
            Entity(id="item", name="Item", prototype_id="object", container_id="box"),
            Entity(id="box", name="Box"),
            Entity(id="object", name="Object"),
        ]
        sorted_entities = _validate_and_sort_entities(entities, set())

        object_idx = next(i for i, e in enumerate(sorted_entities) if e.id == "object")
        box_idx = next(i for i, e in enumerate(sorted_entities) if e.id == "box")
        item_idx = next(i for i, e in enumerate(sorted_entities) if e.id == "item")

        assert object_idx < item_idx
        assert box_idx < item_idx


@pytest.mark.asyncio(loop_scope="module")
class TestSyncEntities:
    """Test syncing entities to database."""

    @pytest_asyncio.fixture(scope="class", loop_scope="module")
    async def synced_db(self, test_db):
        """Sync entities to test database."""
        await sync_entities(test_db)
        yield test_db

    async def test_entities_loaded_to_database(self, synced_db):
        """Entities are inserted into the entities table."""
        async with synced_db.acquire() as conn:
            db_entities = await conn.fetch("SELECT * FROM entities")
            db_entity_ids = {e["id"] for e in db_entities}

            assert "object" in db_entity_ids
            assert "foyer_table" in db_entity_ids

    async def test_prototype_reference_stored(self, synced_db):
        """Prototype references are stored correctly."""
        async with synced_db.acquire() as conn:
            foyer_table = await conn.fetchrow(
                "SELECT * FROM entities WHERE id = $1", "foyer_table"
            )
            assert foyer_table is not None
            assert foyer_table["prototype_id"] == "furniture"

    async def test_container_reference_stored(self, synced_db):
        """Container references are stored correctly."""
        async with synced_db.acquire() as conn:
            foyer_flower_vase = await conn.fetchrow(
                "SELECT * FROM entities WHERE id = $1", "foyer_flower_vase"
            )
            assert foyer_flower_vase is not None
            assert foyer_flower_vase["container_id"] == "foyer_table"

    async def test_resolve_entity_function_works(self, synced_db):
        """The resolve_entity function resolves inherited properties."""
        async with synced_db.acquire() as conn:
            resolved = await conn.fetchrow(
                "SELECT * FROM resolve_entity($1)", "foyer_table"
            )
            assert resolved is not None
            # foyer_table inherits on_touch from object prototype chain
            assert resolved["on_touch"] is not None

    async def test_sync_returns_count(self, test_db):
        """sync_entities returns the number of entities synced."""
        count = await sync_entities(test_db)
        entities = load_entities_from_rec()
        assert count == len(entities)


@pytest.mark.asyncio(loop_scope="module")
class TestSyncRemovesStaleEntities:
    """Test that sync removes entities not in files."""

    async def test_removes_stale_entities(self, test_db):
        """Entities not in rec files are removed on sync."""
        async with test_db.acquire() as conn:
            # Insert a fake entity that should be deleted
            await conn.execute(
                """INSERT INTO entities (id, name, spawn_mode)
                   VALUES ($1, $2, 'none'::spawn_mode)
                   ON CONFLICT (id) DO NOTHING""",
                "fake-entity",
                "Fake Entity",
            )

            # Verify fake entity exists
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM entities WHERE id = $1", "fake-entity"
            )
            assert count == 1

        # Run the sync function - it should delete the fake entity
        await sync_entities(test_db)

        async with test_db.acquire() as conn:
            # Verify fake entity is gone
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM entities WHERE id = $1", "fake-entity"
            )
            assert count == 0
