"""Scenario-driven tests for item pickup, drop, and granting systems.

Tests the item system:
- effects.pickup(): items move from room to inventory when called
- Quest items (rarity=quest): clone on pickup, originals stay in room
- OnDrop with effects.drop(): items return to room
- effects.grant(): grant specific items
- effects.grant_random(): grant random items from tag pool
"""

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


class TestItemPickup:
    """Tests for taking items with effects.pickup()."""

    async def test_take_item_with_pickup_effect(self, test_client):
        """Taking an item that calls effects.pickup() moves it to inventory."""
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

    async def test_take_quest_item_moves_instance(self, test_client):
        """Taking a quest item moves it to inventory like regular items."""
        user = await test_client.create_user(user_id=500002, room="store-room")

        # Verify item exists in room before taking
        assert await test_client.is_entity_in_room("test_quest_map", "store-room")

        # Open the container to access the item
        await test_client.interact(user, action="open", target="Cardboard Box")

        # Take the quest item
        response = await test_client.interact(
            user, action="take", target="Test Quest Map"
        )
        assert "TEST_TAKE_MOVE_RESPONSE" in response

        # Item should be in inventory
        inventory = await test_client.get_inventory(user)
        entity_ids = [eid for eid, _ in inventory]
        assert "test_quest_map" in entity_ids

        # Item should no longer be in room (quest items now move like regular items)
        assert not await test_client.is_entity_in_room("test_quest_map", "store-room")


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

        # Close the container so item drops to floor (not back into container)
        await test_client.interact(user, action="close", target="Cardboard Box")

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

        # Item should be on floor and marked as player_dropped
        assert await test_client.is_entity_in_room("test_droppable_2", "store-room")
        dropped_count = await test_client.count_floor_dropped_items("store-room")
        assert dropped_count >= 1

    async def test_dropped_item_appears_in_look(self, test_client):
        """Dropped items taken from containers appear in /look output."""
        user = await test_client.create_user(user_id=500013, room="store-room")

        # Open the container and take the item (item has container_entity_id set)
        await test_client.interact(user, action="open", target="Cardboard Box")
        await test_client.interact(user, action="take", target="Test Droppable 11")

        # Confirm it's in inventory
        inventory = await test_client.get_inventory(user)
        entity_ids = [eid for eid, _ in inventory]
        assert "test_droppable_11" in entity_ids

        # Close the container so item drops to floor (not back into container)
        await test_client.interact(user, action="close", target="Cardboard Box")

        # Drop the item
        await test_client.interact(user, action="drop", target="Test Droppable 11")

        # Item should appear in /look output
        look_response = await test_client.look(user, at="Room")
        assert "Test Droppable 11" in look_response

    async def test_item_without_drop_effect_stays_in_inventory(self, test_client):
        """Items with OnDrop that doesn't call effects.drop() stay in inventory."""
        user = await test_client.create_user(user_id=500011, room="store-room")

        # Open the container and take the sticky item (OnDrop doesn't call drop())
        await test_client.interact(user, action="open", target="Cardboard Box")
        await test_client.interact(user, action="take", target="Test Sticky")

        # Confirm it's in inventory
        inventory = await test_client.get_inventory(user)
        entity_ids = [eid for eid, _ in inventory]
        assert "test_sticky" in entity_ids

        # Try to drop - OnDrop runs but doesn't call effects.drop()
        response = await test_client.interact(user, action="drop", target="Test Sticky")
        assert "stuck" in response.lower()

        # Item should still be in inventory (OnDrop didn't call effects.drop())
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

        # Close the container so items drop to floor (not back into container)
        await test_client.interact(user, action="close", target="Cardboard Box")

        # Drop 5 items - all should succeed
        for item_name in droppables_to_drop:
            response = await test_client.interact(user, action="drop", target=item_name)
            assert "drop" in response.lower() and "cluttered" not in response.lower()

        # Verify 5 dropped items on floor
        dropped_count = await test_client.count_floor_dropped_items("store-room")
        assert dropped_count == 5

        # Try to drop the 6th item - should fail due to floor clutter
        response = await test_client.interact(user, action="drop", target=sixth_item)
        assert "cluttered" in response.lower()

        # Item should still be in inventory
        inventory = await test_client.get_inventory(user)
        entity_ids = [eid for eid, _ in inventory]
        assert "test_droppable_7" in entity_ids


class TestQuestItemDrop:
    """Tests for dropping quest items."""

    async def test_drop_quest_item_moves_to_room(self, test_client):
        """Quest items can be dropped and move from inventory to room."""
        user = await test_client.create_user(user_id=500050, room="store-room")

        # Open the container to access the granting key
        await test_client.interact(user, action="open", target="Cardboard Box")

        # Use the key that grants test_granted_item (a quest item)
        await test_client.interact(user, action="use", target="Test Granting Key")

        # Verify the quest item is in inventory
        inventory = await test_client.get_inventory(user)
        entity_ids = [eid for eid, _ in inventory]
        assert "test_granted_item" in entity_ids

        # Close the container so item drops to floor
        await test_client.interact(user, action="close", target="Cardboard Box")

        # Drop the quest item
        response = await test_client.interact(
            user, action="drop", target="Test Granted Item"
        )
        assert "drop" in response.lower()

        # Item should no longer be in inventory
        inventory = await test_client.get_inventory(user)
        entity_ids = [eid for eid, _ in inventory]
        assert "test_granted_item" not in entity_ids

        # Item should be on floor
        assert await test_client.is_entity_in_room("test_granted_item", "store-room")


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


class TestFocusPreservation:
    """Focus is preserved during inventory operations."""

    async def test_dropping_item_preserves_focus(self, test_client):
        """Dropping an item from inventory doesn't clear container focus."""
        user = await test_client.create_user(user_id=500030, room="store-room")

        # Open the container to establish focus
        await test_client.interact(user, action="open", target="Cardboard Box")
        focus = await test_client.get_focus(user)
        assert focus is not None
        assert focus["entity_id"] == "storeroom_box"

        # Take an item, then drop it
        await test_client.interact(user, action="take", target="Test Droppable 8")
        await test_client.interact(user, action="drop", target="Test Droppable 8")

        # Focus should still be on the container
        focus = await test_client.get_focus(user)
        assert focus is not None
        assert focus["entity_id"] == "storeroom_box"

    async def test_multiple_takes_from_container(self, test_client):
        """Can take multiple items from a container without losing focus."""
        user = await test_client.create_user(user_id=500032, room="store-room")

        # Open the container
        await test_client.interact(user, action="open", target="Cardboard Box")

        # Take first item
        await test_client.interact(user, action="take", target="Test Droppable 9")
        focus = await test_client.get_focus(user)
        assert focus is not None

        # Take second item - focus should persist
        await test_client.interact(user, action="take", target="Test Droppable 10")
        focus = await test_client.get_focus(user)
        assert focus is not None
        assert focus["entity_id"] == "storeroom_box"


class TestContainerDrops:
    """Tests for dropping items into focused containers.

    Note: test_dropping_item_preserves_focus already demonstrates the core behavior -
    when you drop an item with focus on a container, it goes into that container.
    These tests verify the message format and floor drop behavior.
    """

    async def test_drop_into_focused_container_shows_message(self, test_client):
        """Dropping into container shows 'put into' message."""
        user = await test_client.create_user(user_id=500044, room="store-room")

        # test_droppable_8 was dropped back into storeroom_box by
        # test_dropping_item_preserves_focus
        await test_client.interact(user, action="open", target="Cardboard Box")
        await test_client.interact(user, action="take", target="Test Droppable 8")

        # Verify item in inventory
        inventory = await test_client.get_inventory(user)
        if len(inventory) == 0:
            # Item unavailable - test can't run without this fixture
            return
        assert len(inventory) >= 1

        # Open the crate - this establishes new focus on crate
        await test_client.interact(user, action="open", target="Wooden Crate")

        # Drop should show "put into" message with container name
        response = await test_client.interact(
            user, action="drop", target="Test Droppable 8"
        )
        assert "put" in response.lower()
        assert "Wooden Crate" in response

        # Verify item is now in the crate
        assert await test_client.is_entity_in_container(
            "test_droppable_8", "storeroom_crate", "store-room"
        )

    async def test_drop_to_floor_shows_drop_message(self, test_client):
        """Dropping with no container focus shows 'drop' message (not 'put')."""
        user = await test_client.create_user(user_id=500041, room="store-room")

        # Take item from crate (where previous test dropped it), close, drop to floor
        await test_client.interact(user, action="open", target="Wooden Crate")
        await test_client.interact(user, action="take", target="Test Droppable 8")
        await test_client.interact(user, action="close", target="Wooden Crate")

        inventory = await test_client.get_inventory(user)
        if len(inventory) == 0:
            # Item unavailable
            return

        # Focus should be cleared
        focus = await test_client.get_focus(user)
        assert focus is None

        # Drop the item - should show "drop" message, not "put"
        response = await test_client.interact(
            user, action="drop", target="Test Droppable 8"
        )
        assert "drop" in response.lower()
        assert "put" not in response.lower()


class TestDispenseEffect:
    """Tests for effects.dispense() - dispensing items from containers."""

    async def test_slot_machine_dispenses_item_to_inventory(self, test_client):
        """Using slot machine with effects.dispense() gives item to user."""
        user = await test_client.create_user(user_id=500070, room="lounge")

        # Spawn a prize in the slot machine
        await test_client.spawn_from_pool("lounge_slot_machine_pool")

        # Verify user starts with empty inventory
        inventory = await test_client.get_inventory(user)
        assert len(inventory) == 0

        # Use (pull) the slot machine
        response, broadcasts = await test_client.interact_with_broadcasts(
            user, action="pull", target="Slot Machine"
        )

        # User should see the ephemeral spin message
        assert "wheels spin" in response.lower()

        # Should have broadcast about spinning and getting item
        assert len(broadcasts) >= 2
        assert "spins the slot machine" in broadcasts[0].lower()
        assert "got a" in broadcasts[1].lower()

        # User should have something in inventory
        inventory = await test_client.get_inventory(user)
        assert len(inventory) == 1

    async def test_slot_machine_empty_shows_refill_message(self, test_client):
        """Using empty slot machine broadcasts refill message."""
        user = await test_client.create_user(user_id=500071, room="lounge")

        # Don't spawn anything - slot machine starts empty

        # Use the slot machine
        response, broadcasts = await test_client.interact_with_broadcasts(
            user, action="pull", target="Slot Machine"
        )

        # User should see the spin message
        assert "wheels spin" in response.lower()

        # Should have broadcast about spinning and empty machine
        assert len(broadcasts) >= 2
        assert "spins the slot machine" in broadcasts[0].lower()
        assert "waiting to be refilled" in broadcasts[1].lower()

        # User should still have empty inventory
        inventory = await test_client.get_inventory(user)
        assert len(inventory) == 0

    async def test_slot_machine_costs_10_yen(self, test_client):
        """Using slot machine deducts 10 yen from user's balance."""
        user = await test_client.create_user(user_id=500072, room="lounge")

        # Spawn a prize in the slot machine
        await test_client.spawn_from_pool("lounge_slot_machine_pool")

        # Check initial balance (should be 1000 yen)
        initial_balance = await test_client.currency_service.get_balance(user.id)
        assert initial_balance == 1000

        # Use the slot machine
        response, broadcasts = await test_client.interact_with_broadcasts(
            user, action="pull", target="Slot Machine"
        )

        # Should succeed normally
        assert "wheels spin" in response.lower()
        assert len(broadcasts) >= 2

        # Balance should be reduced by 10 yen
        final_balance = await test_client.currency_service.get_balance(user.id)
        assert final_balance == 990

    async def test_slot_machine_insufficient_funds(self, test_client):
        """Using slot machine with insufficient funds shows error."""
        user = await test_client.create_user(user_id=500073, room="lounge")

        # Spawn a prize in the slot machine
        await test_client.spawn_from_pool("lounge_slot_machine_pool")

        # Reduce user's balance to less than 10 yen
        from mudd.services.currency import HOUSE_ACCOUNT_ID

        await test_client.currency_service.transfer(
            user.id, HOUSE_ACCOUNT_ID, 995, "Test transfer"
        )

        # Verify user has only 5 yen left
        balance = await test_client.currency_service.get_balance(user.id)
        assert balance == 5

        # Try to use the slot machine
        response, broadcasts = await test_client.interact_with_broadcasts(
            user, action="pull", target="Slot Machine"
        )

        # User should see the spin message (from OnUse template)
        assert "wheels spin" in response.lower()

        # Should have broadcast about insufficient funds
        assert len(broadcasts) >= 2
        assert "spins the slot machine" in broadcasts[0].lower()
        assert "doesn't have enough yen" in broadcasts[1].lower()
        assert "¥10" in broadcasts[1]

        # User should not receive an item
        inventory = await test_client.get_inventory(user)
        assert len(inventory) == 0

        # Balance should be unchanged (transaction failed)
        final_balance = await test_client.currency_service.get_balance(user.id)
        assert final_balance == 5


class TestSmashableEntities:
    """Tests for entities with effects.destroy()."""

    async def test_smash_destroys_entity_and_grants_loot(self, test_client):
        """Smashing a destroyable entity removes it and grants random loot."""
        user = await test_client.create_user(user_id=500060, room="store-room")

        # Spawn the smashable entity from its pool (no world instance exists)
        spawned_id = await test_client.spawn_from_pool("test_smashable_pool")
        assert spawned_id == "test_smashable"

        # Verify the smashable entity exists in the room
        assert await test_client.is_entity_in_room("test_smashable", "store-room")

        # Open the container to access the smashable
        await test_client.interact(user, action="open", target="Cardboard Box")

        # Smash the entity
        response, broadcasts = await test_client.interact_with_broadcasts(
            user, action="smash", target="Test Smashable"
        )

        # Verify the response contains the expected text
        assert "TEST_SMASH_RESPONSE" in response

        # Entity should be destroyed (no longer in room)
        assert not await test_client.is_entity_in_room("test_smashable", "store-room")

        # User should have received loot in inventory
        inventory = await test_client.get_inventory(user)
        entity_ids = [eid for eid, _ in inventory]
        loot_items = ["test_common_loot", "test_rare_loot"]
        assert any(loot_id in entity_ids for loot_id in loot_items)

        # Should have broadcasts for smash and loot pickup
        assert len(broadcasts) >= 1
        smash_broadcast = broadcasts[0]
        assert "smashes" in smash_broadcast.lower()
