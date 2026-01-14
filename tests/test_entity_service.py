"""Tests for EntityService.

Tests:
1. get_entity returns resolved entity with inherited properties
2. get_entity returns None for nonexistent entity
3. get_entity caches results
4. get_room_entities returns all instances in a room
5. get_room_entities returns empty list for empty room
6. get_entity_instance returns instance by UUID
7. get_entity_instance returns None for nonexistent UUID
8. get_container_contents returns children of container
9. invalidate_cache clears cached entities
10. Singleton pattern - get_entity_service raises before init
11. Singleton pattern - get_entity_service returns instance after init
"""

from uuid import UUID

import asyncpg
import pytest
import pytest_asyncio

from mudd.services.entity import (
    EntityService,
    get_entity_service,
    init_entity_service,
    is_entity_service_initialized,
)
from mudd.services.entity_loader import sync_entities


@pytest.mark.asyncio(loop_scope="module")
class TestEntityService:
    """Test EntityService methods."""

    @pytest_asyncio.fixture(scope="class", loop_scope="module")
    async def service(self, test_db, world_file):
        """Create EntityService with synced entities."""
        await sync_entities(test_db, world_file)
        service = EntityService()
        # Patch get_pool to use test database
        import mudd.services.entity as entity_module

        original_get_pool = entity_module.get_pool

        async def mock_get_pool() -> asyncpg.Pool:
            return test_db

        entity_module.get_pool = mock_get_pool  # type: ignore[assignment]
        yield service
        entity_module.get_pool = original_get_pool

    async def test_get_entity_returns_resolved_entity(self, service):
        """get_entity returns ResolvedEntity with inherited properties."""
        entity = await service.get_entity("foyer_table")
        assert entity is not None
        assert entity.id == "foyer_table"
        assert entity.name == "Wooden Table"
        # Inherited from object prototype chain
        assert entity.on_touch is not None

    async def test_get_entity_returns_none_for_nonexistent(self, service):
        """get_entity returns None for nonexistent entity."""
        entity = await service.get_entity("nonexistent_entity")
        assert entity is None

    async def test_get_entity_caches_result(self, service):
        """get_entity caches result for subsequent calls."""
        # First call
        entity1 = await service.get_entity("foyer_table")
        assert entity1 is not None

        # Should be cached now
        assert "foyer_table" in service._entity_cache

        # Second call should return cached value
        entity2 = await service.get_entity("foyer_table")
        assert entity1 is entity2  # Same object

    async def test_get_room_entities_returns_instances(self, service):
        """get_room_entities returns all instances in a room."""
        instances = await service.get_room_entities("foyer")
        assert len(instances) > 0

        # Check that we got EntityInstance objects with resolved entities
        for instance in instances:
            assert instance.instance_id is not None
            assert instance.room == "foyer"
            assert instance.entity is not None
            assert instance.entity.name is not None

    async def test_get_room_entities_returns_empty_for_empty_room(self, service):
        """get_room_entities returns empty list for room with no entities."""
        instances = await service.get_room_entities("nonexistent_room")
        assert instances == []

    async def test_get_entity_instance_returns_instance_by_uuid(self, service):
        """get_entity_instance returns instance by UUID."""
        # First get an instance from a room to get a valid UUID
        instances = await service.get_room_entities("foyer")
        assert len(instances) > 0

        instance_id = instances[0].instance_id
        instance = await service.get_entity_instance(instance_id)

        assert instance is not None
        assert instance.instance_id == instance_id
        assert instance.entity is not None

    async def test_get_entity_instance_returns_none_for_nonexistent(self, service):
        """get_entity_instance returns None for nonexistent UUID."""
        fake_uuid = UUID("00000000-0000-0000-0000-000000000000")
        instance = await service.get_entity_instance(fake_uuid)
        assert instance is None

    async def test_get_container_contents_returns_children(self, service):
        """get_container_contents returns children of container."""
        # foyer_table contains foyer_flower_vase and foyer_plaque
        contents = await service.get_container_contents("foyer_table", "foyer")
        assert len(contents) >= 2

        content_entity_ids = {c.entity.id for c in contents}
        assert "foyer_flower_vase" in content_entity_ids
        assert "foyer_plaque" in content_entity_ids

    async def test_get_container_contents_returns_empty_for_empty_container(
        self, service
    ):
        """get_container_contents returns empty list for empty container."""
        # foyer_flower_vase has no children
        contents = await service.get_container_contents("foyer_flower_vase", "foyer")
        assert contents == []

    async def test_invalidate_cache_clears_cache(self, service):
        """invalidate_cache clears the entity cache."""
        # Populate cache
        await service.get_entity("foyer_table")
        assert len(service._entity_cache) > 0

        # Clear cache
        service.invalidate_cache()
        assert len(service._entity_cache) == 0


class TestEntityServiceSingleton:
    """Test singleton pattern for EntityService."""

    def test_get_entity_service_raises_before_init(self):
        """get_entity_service raises RuntimeError before initialization."""
        import mudd.services.entity as entity_module

        # Save current state
        original_service = entity_module._service

        try:
            # Force uninitialized state
            entity_module._service = None

            with pytest.raises(RuntimeError, match="EntityService not initialized"):
                get_entity_service()
        finally:
            # Restore original state
            entity_module._service = original_service

    def test_init_entity_service_creates_singleton(self):
        """init_entity_service creates and returns singleton."""
        import mudd.services.entity as entity_module

        # Save current state
        original_service = entity_module._service

        try:
            # Force uninitialized state
            entity_module._service = None
            assert not is_entity_service_initialized()

            # Initialize
            service = init_entity_service()
            assert service is not None
            assert is_entity_service_initialized()

            # get_entity_service should return same instance
            assert get_entity_service() is service
        finally:
            # Restore original state
            entity_module._service = original_service

    def test_is_entity_service_initialized_reflects_state(self):
        """is_entity_service_initialized returns correct state."""
        import mudd.services.entity as entity_module

        # Save current state
        original_service = entity_module._service

        try:
            entity_module._service = None
            assert not is_entity_service_initialized()

            entity_module._service = EntityService()
            assert is_entity_service_initialized()
        finally:
            entity_module._service = original_service
