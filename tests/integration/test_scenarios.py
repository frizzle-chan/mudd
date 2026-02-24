"""Scenario-driven integration tests for the MUDD game."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mudd.caches import EntityAutocompleteCache
from mudd.cogs.shared import (
    entity_instance_id_autocomplete as raw_autocomplete,
)
from mudd.commands import (
    AttackCommand,
    CloseCommand,
    DropCommand,
    FishCommand,
    LookCommand,
    OpenCommand,
    TakeCommand,
    TouchCommand,
    UseCommand,
)
from mudd.events import (
    BalanceChangedEvent,
    BroadcastEvent,
    EntityDestroyedEvent,
    EntityDroppedEvent,
    EntityPickedUpEvent,
    TradingSessionEndedEvent,
    TradingSessionStartedEvent,
    UserLocationSyncEvent,
    UserMovedEvent,
)
from mudd.models import EntityInstance, RoomEntityInstance, Shop, TradingSession, User
from mudd.models.currency import HOUSE_ACCOUNT_ID, transfer_currency
from mudd.models.shop import purchase_price, sale_price
from mudd.models.spawning_pool import SpawningPool
from mudd.models.user import InsufficientFundsError, TransferError
from mudd.scene import Scene
from mudd.utils.text import Rarity
from tests.helpers import (
    NullReconciler,
    act,
    autocomplete,
    create_test_user,
    move,
)

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

    move_result = await move(test_db, user.id, "store-room", guild_id=GUILD_ID)

    events = move_result.reconciler.events
    assert any(isinstance(e, UserMovedEvent) for e in events)
    assert any(isinstance(e, UserLocationSyncEvent) for e in events)

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
    assert "Test Water Basin" in entity_names
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

    # === FISHING MECHANIC ===

    # Fish without a pole -- should be rejected
    basin = next(
        o
        for o in await autocomplete(test_db, user.id, "Water Basin")
        if not isinstance(o, RoomEntityInstance)
    )
    result = await act(test_db, user.id, FishCommand(), f"entity://{basin.instance_id}")
    assert result.output == "You need a fishing pole to fish."

    # Acquire fishing pole from box
    await act(test_db, user.id, OpenCommand(), f"entity://{box.instance_id}")
    options = await autocomplete(test_db, user.id, "")
    pole = next(
        o
        for o in options
        if not isinstance(o, RoomEntityInstance)
        and o.entity.name == "Test Fishing Pole"
    )
    result = await act(test_db, user.id, TakeCommand(), f"entity://{pole.instance_id}")
    assert any(isinstance(e, EntityPickedUpEvent) for e in result.reconciler.events)
    inv = await autocomplete(test_db, user.id, "i.")
    assert any(e.entity.name == "Test Fishing Pole" for e in inv)

    # Close box, back to room view
    await act(test_db, user.id, CloseCommand(), f"entity://{box.instance_id}")

    # Fish from basin (has a fish inside)
    basin = next(
        o
        for o in await autocomplete(test_db, user.id, "Water Basin")
        if not isinstance(o, RoomEntityInstance)
    )
    result = await act(test_db, user.id, FishCommand(), f"entity://{basin.instance_id}")
    assert "TEST_FISH_RESPONSE" in result.output

    # Fish should now be in inventory
    inv = await autocomplete(test_db, user.id, "i.")
    assert any(e.entity.name == "Test Fish" for e in inv)

    # Fish again from empty basin
    result = await act(test_db, user.id, FishCommand(), f"entity://{basin.instance_id}")
    assert "nothing is biting" in result.output

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
    await move(test_db, player_a.id, "store-room", guild_id=GUILD_ID)

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


async def test_payment_broadcast_and_mentions(test_db, clean_user_state):
    """Payment events broadcast to channel and use mentions in memos."""
    player_a = await create_test_user(test_db, user_id=3001)
    player_b = await create_test_user(test_db, user_id=3002, room_id="store-room")

    # Move player A to store room
    await move(test_db, player_a.id, "store-room", guild_id=1234567890)

    # Create currency accounts
    await User.create_currency_account(test_db, player_a.id, 500)
    await User.create_currency_account(test_db, player_b.id, 100)

    # Transfer with observer to capture events
    reconciler = NullReconciler()
    user_a = await User.get(test_db, player_a.id)
    assert user_a is not None
    user_a = user_a.with_observers(reconciler)
    user_b = await User.get(test_db, player_b.id)
    assert user_b is not None

    transfer_result = await user_a.transfer_currency_to(user_b, 50, "test payment")
    assert transfer_result.success

    # Check that BroadcastEvent was emitted
    broadcast_events = [e for e in reconciler.events if isinstance(e, BroadcastEvent)]
    assert len(broadcast_events) == 1
    assert broadcast_events[0].message == "<@3001> paid ¤50 to <@3002>"

    # Check that BalanceChangedEvents use mentions in memos
    balance_events = [
        e for e in reconciler.events if isinstance(e, BalanceChangedEvent)
    ]
    assert len(balance_events) == 2

    # Find sender and recipient events
    sender_event = next(e for e in balance_events if e.user_id == 3001)
    recipient_event = next(e for e in balance_events if e.user_id == 3002)

    # Check memos use mentions
    assert sender_event.memo == "Payment to <@3002>"
    assert recipient_event.memo == "Payment from <@3001>"


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
    await move(test_db, user.id, "foyer", guild_id=GUILD_ID)

    refreshed = await User.get(test_db, user.id)
    assert refreshed is not None
    assert await refreshed.get_focus() is None


async def test_room_entity_commands_rejected(test_db, clean_user_state):
    """Commands on room entities are rejected with appropriate messages."""
    user = await create_test_user(test_db, room_id="store-room")

    # Take a room entity → rejected (can_pickup is False)
    result = await act(test_db, user.id, TakeCommand(), "room://store-room")
    assert result.output == "You can't take that."

    # Drop a room entity → rejected (can_drop is False)
    result = await act(test_db, user.id, DropCommand(), "room://store-room")
    assert result.output == "You can't drop that."

    # Open a room entity → rejected (is_focusable is False)
    result = await act(test_db, user.id, OpenCommand(), "room://store-room")
    assert result.output == "You can't open that."


async def test_missing_handler_fallback(test_db, clean_user_state):
    """Entity without a specific handler returns 'Nothing happens.'"""
    user = await create_test_user(test_db, room_id="store-room")

    # Open box to access contents
    box = next(
        o
        for o in await autocomplete(test_db, user.id, "Cardboard Box")
        if not isinstance(o, RoomEntityInstance)
    )
    await act(test_db, user.id, OpenCommand(), f"entity://{box.instance_id}")

    # Test Orb inherits from `object` which has no OnOpen handler
    orb = next(
        o
        for o in await autocomplete(test_db, user.id, "")
        if not isinstance(o, RoomEntityInstance) and o.entity.name == "Test Orb"
    )
    result = await act(test_db, user.id, OpenCommand(), f"entity://{orb.instance_id}")
    assert result.output == "Nothing happens."


async def test_wallet_balance_display(test_db, clean_user_state):
    """Looking at wallet displays formatted balance via money filter."""
    user = await create_test_user(test_db, room_id="store-room")
    await User.create_currency_account(test_db, user.id, 1000)

    # Open box, find wallet
    box = next(
        o
        for o in await autocomplete(test_db, user.id, "Cardboard Box")
        if not isinstance(o, RoomEntityInstance)
    )
    await act(test_db, user.id, OpenCommand(), f"entity://{box.instance_id}")

    wallet = next(
        o
        for o in await autocomplete(test_db, user.id, "")
        if not isinstance(o, RoomEntityInstance) and o.entity.name == "Test Wallet"
    )
    result = await act(
        test_db, user.id, LookCommand(), f"entity://{wallet.instance_id}"
    )
    assert "¤1,000" in result.output


async def test_transfer_insufficient_funds(test_db, clean_user_state):
    """Transfer fails with INSUFFICIENT_FUNDS when sender lacks balance."""
    player_a = await create_test_user(test_db, user_id=3001, room_id="store-room")
    player_b = await create_test_user(test_db, user_id=3002, room_id="store-room")

    await User.create_currency_account(test_db, player_a.id, 100)
    await User.create_currency_account(test_db, player_b.id, 0)

    user_a = await User.get(test_db, player_a.id)
    assert user_a is not None
    user_b = await User.get(test_db, player_b.id)
    assert user_b is not None

    transfer = await user_a.transfer_currency_to(user_b, 200, "too much")
    assert not transfer.success
    assert transfer.error == TransferError.INSUFFICIENT_FUNDS
    assert transfer.sender_balance == 100
    assert transfer.recipient_balance == 0


async def test_refresh_focus_extends_timeout(test_db, clean_user_state):
    """Refreshing focus updates timestamp, preventing timeout."""
    user = await create_test_user(test_db, room_id="store-room")

    # Open box to set focus
    box = next(
        o
        for o in await autocomplete(test_db, user.id, "Cardboard Box")
        if not isinstance(o, RoomEntityInstance)
    )
    await act(test_db, user.id, OpenCommand(), f"entity://{box.instance_id}")

    # Backdate focus to 4 minutes ago (just under 5-min timeout)
    async with test_db.acquire() as conn:
        await conn.execute(
            "UPDATE user_focus SET updated_at = $1 WHERE user_id = $2",
            datetime.now(UTC) - timedelta(minutes=4),
            user.id,
        )

    # Refresh focus (updates timestamp to now)
    fresh_user = await User.get(test_db, user.id)
    assert fresh_user is not None
    await fresh_user.refresh_focus()

    # Focus should still be active
    focus = await fresh_user.get_focus()
    assert focus is not None
    assert focus.current_container.entity.name == "Cardboard Box"


async def test_spawning_pool_respawn(test_db, clean_user_state):
    """Spawning pool detects vacancy and spawns replacement entity."""
    user = await create_test_user(test_db, room_id="store-room")

    # Open box, find and destroy test_smashable
    box = next(
        o
        for o in await autocomplete(test_db, user.id, "Cardboard Box")
        if not isinstance(o, RoomEntityInstance)
    )
    await act(test_db, user.id, OpenCommand(), f"entity://{box.instance_id}")

    smashable = next(
        o
        for o in await autocomplete(test_db, user.id, "")
        if not isinstance(o, RoomEntityInstance) and o.entity.name == "Test Smashable"
    )
    await act(test_db, user.id, AttackCommand(), f"entity://{smashable.instance_id}")

    # Close box to exit focus
    await act(test_db, user.id, CloseCommand(), f"entity://{box.instance_id}")

    # Load spawning pools from DB
    pools = await SpawningPool.get_all_with_counts(test_db)
    smashable_pool = next(p for p in pools if p.id == "test_smashable_pool")

    # Pool should detect the vacancy (world instance has no spawning_pool_id)
    assert smashable_pool.current_count == 0
    now = datetime.now(UTC)
    assert smashable_pool.can_spawn(now)

    # Spawn a replacement via the pool
    instance = await smashable_pool.try_spawn(now)
    assert instance is not None
    assert instance.entity.name == "Test Smashable"
    assert instance.room_id == "store-room"

    # Destroy the pool-spawned instance — timer should reset
    await instance.destroy()

    # Re-fetch pool state
    pools = await SpawningPool.get_all_with_counts(test_db)
    smashable_pool = next(p for p in pools if p.id == "test_smashable_pool")
    assert smashable_pool.current_count == 0

    # Timer was just reset, so immediate respawn should be blocked
    now = datetime.now(UTC)
    assert not smashable_pool.can_spawn(now)

    # After the respawn interval elapses, spawning should be allowed
    future = now + timedelta(minutes=smashable_pool.respawn_interval_minutes)
    assert smashable_pool.can_spawn(future)


async def test_focus_timeout_clears_stale_focus(test_db, clean_user_state):
    """Stale focus (>5 min old) is automatically cleared on access."""
    user = await create_test_user(test_db, room_id="store-room")

    # Open box to set focus
    box = next(
        o
        for o in await autocomplete(test_db, user.id, "Cardboard Box")
        if not isinstance(o, RoomEntityInstance)
    )
    await act(test_db, user.id, OpenCommand(), f"entity://{box.instance_id}")

    # Verify focus is set
    fresh_user = await User.get(test_db, user.id)
    assert fresh_user is not None
    assert await fresh_user.get_focus() is not None

    # Backdate focus to 10 minutes ago (well past 5-min timeout)
    async with test_db.acquire() as conn:
        await conn.execute(
            "UPDATE user_focus SET updated_at = $1 WHERE user_id = $2",
            datetime.now(UTC) - timedelta(minutes=10),
            user.id,
        )

    # Focus should now return None (timeout detected, row deleted)
    fresh_user = await User.get(test_db, user.id)
    assert fresh_user is not None
    assert await fresh_user.get_focus() is None

    # Autocomplete should show room entities, not box contents
    options = await autocomplete(test_db, user.id, "")
    entity_names = {
        o.entity.name for o in options if not isinstance(o, RoomEntityInstance)
    }
    assert "Cardboard Box" in entity_names


async def test_other_players_in_room(test_db, clean_user_state):
    """Scene.other_players() returns other users in the same room."""
    user_a = await create_test_user(test_db, user_id=4001, room_id="store-room")
    user_b = await create_test_user(test_db, user_id=4002, room_id="store-room")

    scene = await Scene.from_user(test_db, user_a.id)
    others = await scene.other_players()

    other_ids = [u.id for u in others]
    assert user_b.id in other_ids
    assert user_a.id not in other_ids


async def test_beverage_prototype_chain(test_db, clean_user_state):
    """Beverage prototype chain (beverage -> item -> object) resolves correctly."""
    user = await create_test_user(test_db, room_id="store-room")

    # Open box, find beverage
    box = next(
        o
        for o in await autocomplete(test_db, user.id, "Cardboard Box")
        if not isinstance(o, RoomEntityInstance)
    )
    await act(test_db, user.id, OpenCommand(), f"entity://{box.instance_id}")

    beverage = next(
        o
        for o in await autocomplete(test_db, user.id, "")
        if not isinstance(o, RoomEntityInstance) and o.entity.name == "Test Beverage"
    )

    # Take: beverage has custom OnTake "grabs" (from beverage prototype)
    result = await act(
        test_db, user.id, TakeCommand(), f"entity://{beverage.instance_id}"
    )
    assert "grab" in result.output.lower()
    assert any(isinstance(e, EntityPickedUpEvent) for e in result.reconciler.events)

    # Verify in inventory
    inv = await autocomplete(test_db, user.id, "i.")
    assert any(e.entity.name == "Test Beverage" for e in inv)

    # Use: beverage has custom OnUse "crack open" / "refreshing sip"
    result = await act(
        test_db, user.id, UseCommand(), f"entity://{beverage.instance_id}"
    )
    assert "refreshing sip" in result.output.lower()


async def test_autocomplete_db_fallback_no_user_cache(
    test_db, entity_cache, clean_user_state
):
    """Autocomplete falls back to DB when user_cache is not provided."""
    user = await create_test_user(test_db, room_id="store-room")

    choices = await raw_autocomplete(
        test_db, user.id, "", entity_cache=entity_cache, user_cache=None
    )

    assert len(choices) > 0
    assert any(c.value.startswith("room://") for c in choices)


async def test_autocomplete_db_fallback_user_not_in_cache(
    test_db, entity_cache, user_cache, clean_user_state
):
    """Autocomplete falls back to DB when user is absent from user_cache."""
    # Create user directly (bypasses user_cache.rebuild_user in create_test_user)
    user_id = 888_888
    await User.create_if_not_exists(test_db, user_id, "store-room")

    choices = await raw_autocomplete(
        test_db, user_id, "", entity_cache=entity_cache, user_cache=user_cache
    )

    assert len(choices) > 0
    assert any(c.value.startswith("room://") for c in choices)


async def test_autocomplete_slow_path_entity_cache_miss(
    test_db, user_cache, clean_user_state
):
    """Autocomplete uses slow path when entity_cache has no data for the room."""
    user = await create_test_user(test_db, room_id="store-room")

    # Empty entity cache — get_room_choices returns None for every room
    empty_entity_cache = EntityAutocompleteCache()

    choices = await raw_autocomplete(
        test_db,
        user.id,
        "",
        entity_cache=empty_entity_cache,
        user_cache=user_cache,
    )

    assert len(choices) > 0
    assert any(c.value.startswith("room://") for c in choices)


async def test_autocomplete_thread_cache_hit(test_db, entity_cache, clean_user_state):
    """Autocomplete returns cached thread choices for inventory threads."""
    user = await create_test_user(test_db, room_id="store-room")

    # Take an item so we have an owned entity instance
    box = next(
        o
        for o in await autocomplete(test_db, user.id, "Cardboard Box")
        if not isinstance(o, RoomEntityInstance)
    )
    await act(test_db, user.id, OpenCommand(), f"entity://{box.instance_id}")
    takeable = next(
        o
        for o in await autocomplete(test_db, user.id, "")
        if not isinstance(o, RoomEntityInstance) and o.entity.name == "Test Takeable"
    )
    await act(test_db, user.id, TakeCommand(), f"entity://{takeable.instance_id}")

    # Simulate Discord thread creation by setting thread IDs
    thread_id = 777_777_777
    await EntityInstance.update_thread_ids(
        test_db, takeable.instance_id, thread_id, msg_id=888_888_888
    )

    # Rebuild entity cache so thread choices are populated
    await entity_cache.rebuild(test_db)

    # Autocomplete with thread_id should hit the thread cache
    choices = await raw_autocomplete(
        test_db,
        user.id,
        "",
        thread_id=thread_id,
        entity_cache=entity_cache,
    )

    assert len(choices) == 1
    assert choices[0].value == f"entity://{takeable.instance_id}"
    assert "Test Takeable" in choices[0].name


async def test_cannot_drop_item_not_in_inventory(test_db, clean_user_state):
    """Player cannot drop an item they don't have in inventory."""
    user = await create_test_user(test_db, room_id="store-room")

    # Find an item in the room (not in inventory)
    options = await autocomplete(test_db, user.id, "Cardboard Box")
    box = next(
        o
        for o in options
        if not isinstance(o, RoomEntityInstance) and o.entity.name == "Cardboard Box"
    )

    # Open the box to see contents
    await act(test_db, user.id, OpenCommand(), f"entity://{box.instance_id}")

    # Find a takeable item inside (but don't take it)
    options = await autocomplete(test_db, user.id, "")
    takeable = next(
        o
        for o in options
        if not isinstance(o, RoomEntityInstance) and o.entity.name == "Test Takeable"
    )

    # Try to drop an item that's NOT in inventory (it's in the box)
    result = await act(
        test_db, user.id, DropCommand(), f"entity://{takeable.instance_id}"
    )
    assert result.output == "You don't have that item."

    # Verify no drop event was emitted
    assert not any(isinstance(e, EntityDroppedEvent) for e in result.reconciler.events)

    # Verify item is still in the box (not dropped)
    options = await autocomplete(test_db, user.id, "")
    assert any(
        o.entity.name == "Test Takeable"
        for o in options
        if not isinstance(o, RoomEntityInstance)
    )


async def test_charge_machine_deducts_currency_and_dispenses(test_db, clean_user_state):
    """Charge machine deducts ¤5, dispenses prize, emits balance event."""
    user = await create_test_user(test_db, room_id="store-room")
    await User.create_currency_account(test_db, user.id, 100)

    # Use the charge machine
    machine = next(
        o
        for o in await autocomplete(test_db, user.id, "Charge Machine")
        if not isinstance(o, RoomEntityInstance)
    )
    result = await act(
        test_db, user.id, UseCommand(), f"entity://{machine.instance_id}"
    )

    # Template rendered the success path
    assert "TEST_CHARGE_RESPONSE" in result.output

    # Charge signal was collected by the effects observer
    assert len(result.effects.currency_charges) == 1
    assert result.effects.currency_charges[0] == 5

    # Dispense signal was also fired
    assert result.effects.has_dispense

    # Broadcast was emitted
    assert len(result.effects.broadcasts) > 0
    assert "uses the charge machine" in result.effects.broadcasts[0]

    # Prize should have been picked up into inventory
    inv = await autocomplete(test_db, user.id, "i.")
    assert any(e.entity.name == "Test Charge Prize" for e in inv)

    # Balance should be 100 - 5 = 95
    refreshed = await User.get(test_db, user.id)
    assert refreshed is not None
    assert await refreshed.get_balance() == 95

    # BalanceChangedEvent emitted with negative delta
    balance_events = [
        e for e in result.reconciler.events if isinstance(e, BalanceChangedEvent)
    ]
    charge_event = next(e for e in balance_events if e.delta < 0)
    assert charge_event.delta == -5
    assert charge_event.user_id == user.id


async def test_charge_machine_insufficient_funds(test_db, clean_user_state):
    """Player with insufficient funds sees rejection message, no charge or dispense."""
    user = await create_test_user(test_db, room_id="store-room")
    await User.create_currency_account(test_db, user.id, 3)  # Less than ¤5

    # Use the charge machine
    machine = next(
        o
        for o in await autocomplete(test_db, user.id, "Charge Machine")
        if not isinstance(o, RoomEntityInstance)
    )
    result = await act(
        test_db, user.id, UseCommand(), f"entity://{machine.instance_id}"
    )

    # Template rendered the insufficient funds path
    assert "TEST_INSUFFICIENT_FUNDS" in result.output
    assert "¤3" in result.output

    # No charge or dispense signals were emitted
    assert len(result.effects.currency_charges) == 0
    assert not result.effects.has_dispense

    # Balance unchanged
    refreshed = await User.get(test_db, user.id)
    assert refreshed is not None
    assert await refreshed.get_balance() == 3

    # No prize in inventory
    inv = await autocomplete(test_db, user.id, "i.")
    assert not any(e.entity.name == "Test Charge Prize" for e in inv)


async def test_charge_machine_empty(test_db, clean_user_state):
    """Player uses empty charge machine, sees empty message, no charge."""
    user = await create_test_user(test_db, room_id="store-room")
    await User.create_currency_account(test_db, user.id, 100)

    # Remove the prize from the machine so it's empty
    machine = next(
        o
        for o in await autocomplete(test_db, user.id, "Charge Machine")
        if not isinstance(o, RoomEntityInstance)
    )

    # First use: dispenses the prize (empties the machine)
    await act(test_db, user.id, UseCommand(), f"entity://{machine.instance_id}")

    # Second use: machine should be empty
    result = await act(
        test_db, user.id, UseCommand(), f"entity://{machine.instance_id}"
    )
    assert "empty" in result.output.lower()

    # No charge on the empty attempt
    assert len(result.effects.currency_charges) == 0

    # Balance should be 95 (only first pull charged)
    refreshed = await User.get(test_db, user.id)
    assert refreshed is not None
    assert await refreshed.get_balance() == 95


async def test_debit_to_house_insufficient_funds_error(test_db, clean_user_state):
    """User.debit_to_house raises InsufficientFundsError when balance is too low."""
    user = await create_test_user(test_db, room_id="store-room")
    await User.create_currency_account(test_db, user.id, 10)

    fresh = await User.get(test_db, user.id)
    assert fresh is not None

    with pytest.raises(InsufficientFundsError) as exc_info:
        await fresh.debit_to_house(50, memo="test overcharge")

    assert exc_info.value.balance == 10
    assert exc_info.value.amount == 50

    # Balance unchanged
    assert await fresh.get_balance() == 10


async def test_debit_to_house_success(test_db, clean_user_state):
    """User.debit_to_house deducts correctly and emits BalanceChangedEvent."""
    user = await create_test_user(test_db, room_id="store-room")
    await User.create_currency_account(test_db, user.id, 200)

    reconciler = NullReconciler()
    fresh = await User.get(test_db, user.id)
    assert fresh is not None
    fresh = fresh.with_observers(reconciler)

    new_balance = await fresh.debit_to_house(75, memo="test debit")
    assert new_balance == 125

    # Balance persisted
    assert await fresh.get_balance() == 125

    # BalanceChangedEvent emitted with negative delta
    balance_events = [
        e for e in reconciler.events if isinstance(e, BalanceChangedEvent)
    ]
    assert len(balance_events) == 1
    assert balance_events[0].user_id == user.id
    assert balance_events[0].new_balance == 125
    assert balance_events[0].delta == -75
    assert balance_events[0].memo == "test debit"


async def test_shop_buy_and_sell(test_db, clean_user_state):
    """Player interacts with merchant, buys an item, then sells it back."""
    # === SETUP ===
    user = await create_test_user(test_db, room_id="store-room")
    await User.create_currency_account(test_db, user.id, 500)

    # === USE MERCHANT → triggers shop signal ===
    merchant = next(
        o
        for o in await autocomplete(test_db, user.id, "Test Merchant")
        if not isinstance(o, RoomEntityInstance)
    )
    result = await act(
        test_db, user.id, UseCommand(), f"entity://{merchant.instance_id}"
    )
    assert result.effects.has_shop
    assert result.effects.shop_id == "test-shop"
    assert any(
        isinstance(e, TradingSessionStartedEvent) for e in result.reconciler.events
    )

    # === CREATE TRADING SESSION (prod: ShopReconciler; tests: manual) ===
    session = await TradingSession.create(
        test_db, user.id, "test-shop", thread_id=99999, overview_message_id=88888
    )
    assert session.shop_id == "test-shop"

    # === STOCK AN ITEM ===
    item = await EntityInstance.create(test_db, "test_shop_item")
    assert item is not None
    await Shop.add_to_stock(test_db, "test-shop", item.instance_id)

    stock = await Shop.get_stock(test_db, "test-shop")
    assert any(s.entity_instance_id == item.instance_id for s in stock)

    # === BUY: player pays house, item moves to inventory ===
    price = purchase_price(Rarity.COMMON, 1, 1)
    assert price == 100  # base=100, supply_adj=1.0, speech discount=0

    async with test_db.acquire() as conn, conn.transaction():
        await transfer_currency(
            conn,
            from_id=user.id,
            to_id=HOUSE_ACCOUNT_ID,
            amount=price,
            memo="Buy Test Shop Item",
        )

    await Shop.remove_from_stock(test_db, item.instance_id)

    # Re-fetch with observers to capture events
    fresh_item = await EntityInstance.get(test_db, item.instance_id)
    assert fresh_item is not None
    reconciler = NullReconciler()
    fresh_item = fresh_item.with_observers(reconciler)

    fresh_user = await User.get(test_db, user.id)
    assert fresh_user is not None
    fresh_item = await fresh_item.move_to_inventory(fresh_user)

    # Assert buy results
    assert await fresh_user.get_balance() == 400
    inv = await EntityInstance.get_by_owner(test_db, user.id)
    assert any(i.instance_id == item.instance_id for i in inv)
    stock = await Shop.get_stock(test_db, "test-shop")
    assert not any(s.entity_instance_id == item.instance_id for s in stock)
    assert any(isinstance(e, EntityPickedUpEvent) for e in reconciler.events)

    # === SELL: player receives currency, item returns to stock ===
    # sale_price(common, count=0, speech=1, spread=0.5, preferred=False)
    # = dynamic_price(common, 0) * 0.5 = 100 * 1.0 * 0.5 = 50
    # floor = 100 * 0.25 = 25 → max(50, 25) = 50
    sell = sale_price(Rarity.COMMON, 0, 1, 0.5, False)
    assert sell == 50

    async with test_db.acquire() as conn, conn.transaction():
        await transfer_currency(
            conn,
            from_id=HOUSE_ACCOUNT_ID,
            to_id=user.id,
            amount=sell,
            memo="Sell Test Shop Item",
            require_funds=False,
        )

    # Detach from inventory with fresh observers
    sell_reconciler = NullReconciler()
    owned_item = await EntityInstance.get(test_db, item.instance_id)
    assert owned_item is not None
    owned_item = owned_item.with_observers(sell_reconciler)
    await owned_item.detach_from_inventory()
    await Shop.add_to_stock(test_db, "test-shop", item.instance_id)

    # Assert sell results
    fresh_user = await User.get(test_db, user.id)
    assert fresh_user is not None
    assert await fresh_user.get_balance() == 450
    inv = await EntityInstance.get_by_owner(test_db, user.id)
    assert not any(i.instance_id == item.instance_id for i in inv)
    stock = await Shop.get_stock(test_db, "test-shop")
    assert any(s.entity_instance_id == item.instance_id for s in stock)
    assert any(isinstance(e, EntityDroppedEvent) for e in sell_reconciler.events)

    # === NET LOSS: spread acts as currency sink ===
    final_balance = await fresh_user.get_balance()
    assert final_balance == 450
    assert final_balance < 500  # net loss from spread


async def test_move_ends_trading_session(test_db, clean_user_state):
    """Moving to another room emits TradingSessionEndedEvent with thread_id."""
    user = await create_test_user(test_db, room_id="store-room")

    # Create an active trading session
    thread_id = 55555
    await TradingSession.create(
        test_db, user.id, "test-shop", thread_id=thread_id, overview_message_id=88888
    )

    # Move away — should end the trading session
    result = await move(test_db, user.id, "foyer", guild_id=GUILD_ID)

    ended_events = [
        e for e in result.reconciler.events if isinstance(e, TradingSessionEndedEvent)
    ]
    assert len(ended_events) == 1
    assert ended_events[0].thread_id == thread_id
    assert ended_events[0].user_id == user.id

    # Session should be gone from DB
    session = await TradingSession.get(test_db, user.id)
    assert session is None
