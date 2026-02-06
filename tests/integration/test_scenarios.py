"""Scenario-driven integration tests for the MUDD game."""

from __future__ import annotations

import pytest

from mudd.commands import (
    AttackCommand,
    CloseCommand,
    DropCommand,
    LookCommand,
    OpenCommand,
    TakeCommand,
    TouchCommand,
    UseCommand,
)
from mudd.events import (
    BalanceChangedEvent,
    EntityDestroyedEvent,
    EntityDroppedEvent,
    EntityPickedUpEvent,
    UserLocationSyncEvent,
    UserMovedEvent,
)
from mudd.models import RoomEntityInstance, User
from tests.helpers import NullReconciler, act, autocomplete, create_test_user

# All tests share the session event loop with the session-scoped test_db pool
pytestmark = pytest.mark.asyncio(loop_scope="session")

GUILD_ID = 12345


async def test_new_player_explores_the_world(test_db, clean_user_state):
    """A new player spawns in the Foyer, explores, interacts with entities."""
    user = await create_test_user(test_db)

    # === FOYER (default spawn) ===

    # Player looks at the room
    result = await act(test_db, user.id, LookCommand(), f"room://{user.current_room}")
    assert "test foyer" in result.output.lower()

    # Autocomplete shows only the room entity (no entities in foyer)
    options = await autocomplete(test_db, user.id, "")
    entities = [o for o in options if not isinstance(o, RoomEntityInstance)]
    assert len(entities) == 0

    # Inventory is empty
    inv = await autocomplete(test_db, user.id, "i.")
    assert len(inv) == 0

    # === MOVE TO STORE ROOM ===

    reconciler = NullReconciler()
    fresh_user = await User.get(test_db, user.id)
    assert fresh_user is not None
    user_with_obs = fresh_user.with_observers(reconciler)
    await user_with_obs.move_to("store-room", guild_id=GUILD_ID)

    assert any(isinstance(e, UserMovedEvent) for e in reconciler.events)
    assert any(isinstance(e, UserLocationSyncEvent) for e in reconciler.events)

    # === STORE ROOM: LOOK AROUND ===

    result = await act(test_db, user.id, LookCommand(), "room://store-room")
    assert "store room" in result.output.lower()

    # Autocomplete shows top-level entities
    options = await autocomplete(test_db, user.id, "")
    entity_names = {
        o.entity.name for o in options if not isinstance(o, RoomEntityInstance)
    }
    assert "Cardboard Box" in entity_names
    assert "Wooden Crate" in entity_names
    assert "Test Table" in entity_names
    assert "Test Dispenser" in entity_names
    assert "Test Terminal" in entity_names
    # Items inside opaque containers should NOT be visible
    assert "Test Orb" not in entity_names
    # But Test Painting IS visible (on table with contents_visible=yes)
    assert "Test Painting" in entity_names

    # === LOOK AT SPECIFIC ENTITIES ===

    # Search by partial name
    results = await autocomplete(test_db, user.id, "card")
    assert any(e.entity.name == "Cardboard Box" for e in results)

    # === OPEN THE CARDBOARD BOX ===

    box = next(
        o
        for o in options
        if not isinstance(o, RoomEntityInstance) and o.entity.name == "Cardboard Box"
    )
    result = await act(test_db, user.id, OpenCommand(), f"entity://{box.instance_id}")
    assert "open" in result.output.lower()

    # Focus is now set -- autocomplete shows box contents + [Close] Room
    options = await autocomplete(test_db, user.id, "")
    assert isinstance(options[0], RoomEntityInstance)  # [Close] room option
    content_names = {
        o.entity.name for o in options if not isinstance(o, RoomEntityInstance)
    }
    assert "Test Orb" in content_names
    assert "Test Takeable" in content_names
    assert "Test Granting Key" in content_names

    # === LOOK INSIDE THE BOX ===

    orb = next(
        o
        for o in options
        if not isinstance(o, RoomEntityInstance) and o.entity.name == "Test Orb"
    )
    result = await act(test_db, user.id, LookCommand(), f"entity://{orb.instance_id}")
    assert "TEST_LOOK_RESPONSE" in result.output

    # === INTERACT WITH ENTITIES (touch, attack, use) ===

    # Touch the orb
    result = await act(test_db, user.id, TouchCommand(), f"entity://{orb.instance_id}")
    assert "TEST_TOUCH_RESPONSE" in result.output

    # Attack the orb
    result = await act(test_db, user.id, AttackCommand(), f"entity://{orb.instance_id}")
    assert "TEST_ATTACK_RESPONSE" in result.output

    # Use the gadget
    gadget = next(
        o
        for o in options
        if not isinstance(o, RoomEntityInstance) and o.entity.name == "Test Gadget"
    )
    result = await act(test_db, user.id, UseCommand(), f"entity://{gadget.instance_id}")
    assert "TEST_USE_RESPONSE" in result.output

    # Use the record (has broadcast effect)
    record = next(
        o
        for o in options
        if not isinstance(o, RoomEntityInstance) and o.entity.name == "Test Record"
    )
    result = await act(test_db, user.id, UseCommand(), f"entity://{record.instance_id}")
    assert "TEST_EPHEMERAL_RESPONSE" in result.output
    assert len(result.effects.broadcasts) > 0
    assert "TEST_BROADCAST_RESPONSE" in result.effects.broadcasts[0]

    # === TAKE AN ITEM ===

    takeable = next(
        o
        for o in options
        if not isinstance(o, RoomEntityInstance) and o.entity.name == "Test Takeable"
    )
    result = await act(
        test_db, user.id, TakeCommand(), f"entity://{takeable.instance_id}"
    )
    assert "TEST_TAKE_MOVE_RESPONSE" in result.output
    assert any(isinstance(e, EntityPickedUpEvent) for e in result.reconciler.events)

    # Item now in inventory
    inv = await autocomplete(test_db, user.id, "i.")
    assert any(e.entity.name == "Test Takeable" for e in inv)

    # Item no longer in box contents
    options = await autocomplete(test_db, user.id, "")
    content_names = {
        o.entity.name for o in options if not isinstance(o, RoomEntityInstance)
    }
    assert "Test Takeable" not in content_names

    # === CLOSE THE BOX ===

    result = await act(test_db, user.id, CloseCommand(), f"entity://{box.instance_id}")

    # Back to room view
    options = await autocomplete(test_db, user.id, "")
    entity_names = {
        o.entity.name for o in options if not isinstance(o, RoomEntityInstance)
    }
    assert "Cardboard Box" in entity_names  # room-level entities again
    assert "Test Orb" not in entity_names  # box contents hidden again

    # === DROP AN ITEM ===

    result = await act(
        test_db, user.id, DropCommand(), f"entity://{takeable.instance_id}"
    )
    assert any(isinstance(e, EntityDroppedEvent) for e in result.reconciler.events)

    # Item back on the floor (visible at room level)
    options = await autocomplete(test_db, user.id, "")
    entity_names = {
        o.entity.name for o in options if not isinstance(o, RoomEntityInstance)
    }
    assert "Test Takeable" in entity_names

    # === DESTROY AN ENTITY (SMASH) ===

    # Open box, find smashable
    await act(test_db, user.id, OpenCommand(), f"entity://{box.instance_id}")
    options = await autocomplete(test_db, user.id, "")
    smashable = next(
        o
        for o in options
        if not isinstance(o, RoomEntityInstance) and o.entity.name == "Test Smashable"
    )
    smashable_id = smashable.instance_id

    result = await act(test_db, user.id, AttackCommand(), f"entity://{smashable_id}")
    assert "TEST_SMASH_RESPONSE" in result.output
    assert any(isinstance(e, EntityDestroyedEvent) for e in result.reconciler.events)
    assert len(result.effects.broadcasts) > 0

    # Smashable is gone from autocomplete
    options = await autocomplete(test_db, user.id, "")
    assert not any(
        not isinstance(o, RoomEntityInstance) and o.instance_id == smashable_id
        for o in options
    )

    # === CLOSE BOX, USE THE DISPENSER ===

    await act(test_db, user.id, CloseCommand(), f"entity://{box.instance_id}")

    # Use dispenser
    dispenser = next(
        o
        for o in await autocomplete(test_db, user.id, "Dispenser")
        if not isinstance(o, RoomEntityInstance)
    )
    result = await act(
        test_db, user.id, UseCommand(), f"entity://{dispenser.instance_id}"
    )
    assert "TEST_DISPENSE_RESPONSE" in result.output

    # Prize should have been picked up
    inv = await autocomplete(test_db, user.id, "i.")
    assert any(e.entity.name == "Test Dispenser Prize" for e in inv)

    # === TERMINAL FOCUS (open/read/close) ===

    terminal = next(
        o
        for o in await autocomplete(test_db, user.id, "Terminal")
        if not isinstance(o, RoomEntityInstance)
    )
    result = await act(
        test_db, user.id, OpenCommand(), f"entity://{terminal.instance_id}"
    )
    assert "Welcome to the test terminal" in result.output

    # Focus on terminal -- see document inside
    options = await autocomplete(test_db, user.id, "")
    doc = next(
        o
        for o in options
        if not isinstance(o, RoomEntityInstance) and o.entity.name == "Test Document"
    )
    result = await act(test_db, user.id, LookCommand(), f"entity://{doc.instance_id}")
    assert "test document" in result.output.lower()

    # Close terminal
    result = await act(
        test_db, user.id, CloseCommand(), f"entity://{terminal.instance_id}"
    )
    assert "Logging out" in result.output


async def test_currency_system(test_db, clean_user_state):
    """Player picks up coins (grant_currency), checks wallet, pays another player."""
    player_a = await create_test_user(test_db, user_id=2001)
    player_b = await create_test_user(test_db, user_id=2002, room_id="store-room")

    # Move player A to store room
    user_a = await User.get(test_db, player_a.id)
    assert user_a is not None
    await user_a.move_to("store-room", guild_id=GUILD_ID)

    # Create currency accounts
    await User.create_currency_account(test_db, player_a.id, 500)
    await User.create_currency_account(test_db, player_b.id, 0)

    # Open box, find coins
    box = next(
        o
        for o in await autocomplete(test_db, player_a.id, "Cardboard Box")
        if not isinstance(o, RoomEntityInstance)
    )
    await act(test_db, player_a.id, OpenCommand(), f"entity://{box.instance_id}")

    coins = next(
        o
        for o in await autocomplete(test_db, player_a.id, "")
        if not isinstance(o, RoomEntityInstance) and o.entity.name == "Test Coins"
    )
    result = await act(
        test_db, player_a.id, TakeCommand(), f"entity://{coins.instance_id}"
    )
    assert "TEST_CURRENCY_RESPONSE" in result.output
    # Coins destroyed + currency granted
    assert any(isinstance(e, EntityDestroyedEvent) for e in result.reconciler.events)

    # Balance increased by 100
    refreshed_a = await User.get(test_db, player_a.id)
    assert refreshed_a is not None
    assert await refreshed_a.get_balance() == 600  # 500 + 100

    # Transfer to player B
    reconciler = NullReconciler()
    refreshed_a = refreshed_a.with_observers(reconciler)
    refreshed_b = await User.get(test_db, player_b.id)
    assert refreshed_b is not None
    transfer_result = await refreshed_a.transfer_currency_to(
        refreshed_b, 200, "test payment"
    )
    assert transfer_result.success

    refreshed_a = await User.get(test_db, player_a.id)
    assert refreshed_a is not None
    refreshed_b = await User.get(test_db, player_b.id)
    assert refreshed_b is not None
    assert await refreshed_a.get_balance() == 400
    assert await refreshed_b.get_balance() == 200

    balance_events = [
        e for e in reconciler.events if isinstance(e, BalanceChangedEvent)
    ]
    assert len(balance_events) == 2


async def test_grant_and_grant_random(test_db, clean_user_state):
    """Player uses the granting key (grant specific item)."""
    user = await create_test_user(test_db, room_id="store-room")

    # Open box, find granting key
    box = next(
        o
        for o in await autocomplete(test_db, user.id, "Cardboard Box")
        if not isinstance(o, RoomEntityInstance)
    )
    await act(test_db, user.id, OpenCommand(), f"entity://{box.instance_id}")

    key = next(
        o
        for o in await autocomplete(test_db, user.id, "")
        if not isinstance(o, RoomEntityInstance)
        and o.entity.name == "Test Granting Key"
    )
    result = await act(test_db, user.id, UseCommand(), f"entity://{key.instance_id}")
    assert "TEST_GRANT_RESPONSE" in result.output

    # Granted item should be in inventory
    inv = await autocomplete(test_db, user.id, "i.")
    assert any(e.entity.name == "Test Granted Item" for e in inv)


async def test_sticky_item_cannot_be_dropped(test_db, clean_user_state):
    """Player takes sticky item, tries to drop it, item stays in inventory."""
    user = await create_test_user(test_db, room_id="store-room")

    # Open box, take sticky
    box = next(
        o
        for o in await autocomplete(test_db, user.id, "Cardboard Box")
        if not isinstance(o, RoomEntityInstance)
    )
    await act(test_db, user.id, OpenCommand(), f"entity://{box.instance_id}")

    sticky = next(
        o
        for o in await autocomplete(test_db, user.id, "")
        if not isinstance(o, RoomEntityInstance) and o.entity.name == "Test Sticky"
    )
    await act(test_db, user.id, TakeCommand(), f"entity://{sticky.instance_id}")

    # Close box first, then try to drop
    await act(test_db, user.id, CloseCommand(), f"entity://{box.instance_id}")
    result = await act(
        test_db, user.id, DropCommand(), f"entity://{sticky.instance_id}"
    )
    assert "stuck" in result.output.lower()
    assert not result.effects.has_drop

    # Still in inventory
    inv = await autocomplete(test_db, user.id, "i.")
    assert any(e.entity.name == "Test Sticky" for e in inv)


async def test_painting_visible_on_table_and_destroyable(test_db, clean_user_state):
    """Painting visible on table (contents_visible=yes), take it, slash to destroy."""
    user = await create_test_user(test_db, room_id="store-room")

    # Painting visible in room autocomplete (on table with contents_visible=yes)
    options = await autocomplete(test_db, user.id, "")
    assert any(
        not isinstance(o, RoomEntityInstance) and o.entity.name == "Test Painting"
        for o in options
    )

    # Take the painting
    painting = next(
        o
        for o in options
        if not isinstance(o, RoomEntityInstance) and o.entity.name == "Test Painting"
    )
    result = await act(
        test_db, user.id, TakeCommand(), f"entity://{painting.instance_id}"
    )
    assert any(isinstance(e, EntityPickedUpEvent) for e in result.reconciler.events)

    # Attack to destroy
    result = await act(
        test_db, user.id, AttackCommand(), f"entity://{painting.instance_id}"
    )
    assert any(isinstance(e, EntityDestroyedEvent) for e in result.reconciler.events)
    assert len(result.effects.broadcasts) > 0

    # Gone from inventory
    inv = await autocomplete(test_db, user.id, "i.")
    assert not any(e.entity.name == "Test Painting" for e in inv)


async def test_empty_crate(test_db, clean_user_state):
    """Opening an empty container shows 'empty' message."""
    user = await create_test_user(test_db, room_id="store-room")
    crate = next(
        o
        for o in await autocomplete(test_db, user.id, "Wooden Crate")
        if not isinstance(o, RoomEntityInstance)
    )
    result = await act(test_db, user.id, OpenCommand(), f"entity://{crate.instance_id}")
    assert "empty" in result.output.lower()


async def test_move_back_to_foyer_clears_focus(test_db, clean_user_state):
    """Moving to another room clears focus."""
    user = await create_test_user(test_db, room_id="store-room")

    # Open box to set focus
    box = next(
        o
        for o in await autocomplete(test_db, user.id, "Cardboard Box")
        if not isinstance(o, RoomEntityInstance)
    )
    await act(test_db, user.id, OpenCommand(), f"entity://{box.instance_id}")

    # Move -- focus should clear
    u = await User.get(test_db, user.id)
    assert u is not None
    await u.move_to("foyer", guild_id=GUILD_ID)

    refreshed = await User.get(test_db, user.id)
    assert refreshed is not None
    assert await refreshed.get_focus() is None
