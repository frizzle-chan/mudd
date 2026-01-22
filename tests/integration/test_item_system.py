"""Scenario-driven tests for item pickup, drop, and granting systems.

Tests the item system implemented per ADR 0004:
- spawn_mode=move: items move from room to inventory
- spawn_mode=clone: quest items clone on pickup
- OnDrop with effects.drop(): items return to room
- effects.grant(): grant specific items
- effects.grant_random(): grant random items from tag pool
"""

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


class TestItemPickup:
    """Tests for taking items with different spawn modes."""

    async def test_take_spawn_mode_move_item(self, test_client):
        """Taking an item with spawn_mode=move moves it to inventory."""
        user = await test_client.create_user(user_id=500001, room="store-room")

        # Verify item exists in room before taking
        assert await test_client.is_entity_in_room("test_takeable", "store-room")

        # Open the container to access the item
        await test_client.interact(user, action="open", target="Cardboard Box")

        # Take the item
        response = await test_client.interact(
            user, action="take", target="Test Takeable"
        )
        assert "TEST_TAKE_MOVE_RESPONSE" in response

        # Item should be in inventory
        inventory = await test_client.get_inventory(user)
        entity_ids = [eid for eid, _ in inventory]
        assert "test_takeable" in entity_ids

        # Item should no longer be in room
        assert not await test_client.is_entity_in_room("test_takeable", "store-room")

    async def test_take_spawn_mode_clone_quest_item(self, test_client):
        """Taking a quest item with spawn_mode=clone copies it to inventory."""
        user = await test_client.create_user(user_id=500002, room="store-room")

        # Verify item exists in room before taking
        assert await test_client.is_entity_in_room("test_quest_map", "store-room")

        # Open the container to access the item
        await test_client.interact(user, action="open", target="Cardboard Box")

        # Take the quest item
        response = await test_client.interact(
            user, action="take", target="Test Quest Map"
        )
        assert "TEST_TAKE_CLONE_RESPONSE" in response

        # Item should be in inventory
        inventory = await test_client.get_inventory(user)
        entity_ids = [eid for eid, _ in inventory]
        assert "test_quest_map" in entity_ids

        # Original item should still be in room (clone behavior)
        assert await test_client.is_entity_in_room("test_quest_map", "store-room")

    async def test_cannot_take_quest_item_twice(self, test_client):
        """Taking a quest item you already have returns an error."""
        user = await test_client.create_user(user_id=500003, room="store-room")

        # Open the container
        await test_client.interact(user, action="open", target="Cardboard Box")

        # Take the quest item first time
        response = await test_client.interact(
            user, action="take", target="Test Quest Map"
        )
        assert "TEST_TAKE_CLONE_RESPONSE" in response

        # Confirm it's in inventory
        inventory = await test_client.get_inventory(user)
        entity_ids = [eid for eid, _ in inventory]
        assert "test_quest_map" in entity_ids

        # Try to take again
        response = await test_client.interact(
            user, action="take", target="Test Quest Map"
        )
        assert "already have" in response.lower()


class TestItemDrop:
    """Tests for dropping items from inventory."""

    async def test_drop_item_with_on_drop_handler(self, test_client):
        """Dropping an item with OnDrop handler that calls effects.drop() works."""
        user = await test_client.create_user(user_id=500010, room="store-room")

        # Open the container and take the droppable item
        # Use test_droppable_2 to preserve test_droppable for other tests
        await test_client.interact(user, action="open", target="Cardboard Box")
        await test_client.interact(user, action="take", target="Test Droppable 2")

        # Confirm it's in inventory
        inventory = await test_client.get_inventory(user)
        entity_ids = [eid for eid, _ in inventory]
        assert "test_droppable_2" in entity_ids

        # Drop the item
        response = await test_client.interact(
            user, action="drop", target="Test Droppable 2"
        )
        # The numbered droppables don't have TEST_DROP_RESPONSE
        assert "drop" in response.lower()

        # Item should no longer be in inventory
        inventory = await test_client.get_inventory(user)
        entity_ids = [eid for eid, _ in inventory]
        assert "test_droppable_2" not in entity_ids

        # Item should be in room and marked as player_dropped
        assert await test_client.is_entity_in_room("test_droppable_2", "store-room")
        dropped_count = await test_client.count_player_dropped_items("store-room")
        assert dropped_count >= 1

    async def test_cannot_drop_item_without_on_drop_handler(self, test_client):
        """Items without OnDrop handler can't be dropped."""
        user = await test_client.create_user(user_id=500011, room="store-room")

        # Open the container and take the sticky item (no OnDrop)
        await test_client.interact(user, action="open", target="Cardboard Box")
        await test_client.interact(user, action="take", target="Test Sticky")

        # Confirm it's in inventory
        inventory = await test_client.get_inventory(user)
        entity_ids = [eid for eid, _ in inventory]
        assert "test_sticky" in entity_ids

        # Try to drop - should get "Nothing happens" (no OnDrop handler)
        response = await test_client.interact(user, action="drop", target="Test Sticky")
        assert "nothing happens" in response.lower()

        # Item should still be in inventory
        inventory = await test_client.get_inventory(user)
        entity_ids = [eid for eid, _ in inventory]
        assert "test_sticky" in entity_ids

    async def test_floor_clutter_limit_blocks_sixth_drop(self, test_client):
        """Cannot drop more than 5 items on the floor in one room."""
        user = await test_client.create_user(user_id=500012, room="store-room")

        # Open the container to access items
        await test_client.interact(user, action="open", target="Cardboard Box")

        # Take 6 different droppable items (test_droppable_2 consumed by earlier test)
        # Using test_droppable, 3, 4, 5, 6, and 7
        droppables_to_drop = [
            "Test Droppable 3",
            "Test Droppable 4",
            "Test Droppable 5",
            "Test Droppable 6",
            "Test Droppable",  # 5th item to drop
        ]
        sixth_item = "Test Droppable 7"  # This one will fail to drop

        # Take all 6 items
        for item_name in droppables_to_drop + [sixth_item]:
            await test_client.interact(user, action="take", target=item_name)

        # Verify all 6 items are in inventory
        inventory = await test_client.get_inventory(user)
        assert len(inventory) == 6

        # Drop 5 items - all should succeed
        for item_name in droppables_to_drop:
            response = await test_client.interact(user, action="drop", target=item_name)
            assert "drop" in response.lower() and "cluttered" not in response.lower()

        # Verify 5 dropped items
        dropped_count = await test_client.count_player_dropped_items("store-room")
        assert dropped_count == 5

        # Try to drop the 6th item - should fail due to floor clutter
        response = await test_client.interact(user, action="drop", target=sixth_item)
        assert "cluttered" in response.lower()

        # Item should still be in inventory
        inventory = await test_client.get_inventory(user)
        entity_ids = [eid for eid, _ in inventory]
        assert "test_droppable_7" in entity_ids


class TestItemGranting:
    """Tests for effects.grant() and effects.grant_random()."""

    async def test_effects_grant_gives_specific_item(self, test_client):
        """Using an entity with effects.grant() gives a specific item."""
        user = await test_client.create_user(user_id=500020, room="store-room")

        # Verify user starts with empty inventory
        inventory = await test_client.get_inventory(user)
        assert len(inventory) == 0

        # Open the container to access the granting key
        await test_client.interact(user, action="open", target="Cardboard Box")

        # Use the key that grants test_granted_item
        response = await test_client.interact(
            user, action="use", target="Test Granting Key"
        )
        assert "TEST_GRANT_RESPONSE" in response

        # Should have the granted item in inventory
        inventory = await test_client.get_inventory(user)
        entity_ids = [eid for eid, _ in inventory]
        assert "test_granted_item" in entity_ids

    async def test_effects_grant_random_gives_item_and_broadcasts(self, test_client):
        """Opening entity with grant_random() gives random loot and broadcasts."""
        user = await test_client.create_user(user_id=500021, room="store-room")

        # Verify user starts with empty inventory
        inventory = await test_client.get_inventory(user)
        assert len(inventory) == 0

        # Open the container to access the random grantor
        await test_client.interact(user, action="open", target="Cardboard Box")

        # Open the random grantor chest
        response, broadcasts = await test_client.interact_with_broadcasts(
            user, action="open", target="Test Random Grantor"
        )
        assert "TEST_RANDOM_GRANT_RESPONSE" in response

        # Should have one of the loot items in inventory
        inventory = await test_client.get_inventory(user)
        entity_ids = [eid for eid, _ in inventory]
        loot_items = ["test_common_loot", "test_rare_loot"]
        assert any(loot_id in entity_ids for loot_id in loot_items)

        # Should have a broadcast message about picking up the item
        assert len(broadcasts) >= 1
        # Broadcast should mention the item name
        broadcast = broadcasts[0]
        assert "picks up" in broadcast.lower()
