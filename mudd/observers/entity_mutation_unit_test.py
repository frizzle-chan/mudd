"""Unit tests for EntityMutationObserver."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest

from mudd.events import EntityDestroyedEvent, EntityDroppedEvent, EntityPickedUpEvent
from mudd.models.entity import EntityInstance, ResolvedEntity
from mudd.observers.entity_mutation import EntityMutationObserver
from mudd.utils.text import Rarity


def _make_entity(name: str, rarity: Rarity = "common") -> ResolvedEntity:
    return ResolvedEntity(
        id=f"test::{name}",
        name=name,
        description_short=None,
        description_long=None,
        on_look=None,
        on_touch=None,
        on_attack=None,
        on_use=None,
        on_take=None,
        on_open=None,
        on_close=None,
        on_drop=None,
        contents_visible=False,
        rarity=rarity,
    )


def _make_instance(name: str) -> EntityInstance:
    return EntityInstance(
        instance_id=uuid4(),
        entity=_make_entity(name),
        room_id="test-room",
        owner_id=None,
    )


class TestNotify:
    """Tests for EntityMutationObserver.notify()."""

    def test_pickup_uses_scene_room(self):
        """EntityPickedUpEvent uses the scene's room_id."""
        changed: list[str] = []
        observer = EntityMutationObserver(
            room_id="lobby",
            on_room_changed=changed.append,
            on_rebuild=lambda _: None,
        )
        entity = _make_instance("Sword")
        picked_up = replace(entity, room_id=None, owner_id=12345)

        observer.notify(EntityPickedUpEvent(instance=picked_up))

        assert changed == ["lobby"]

    def test_drop_uses_entity_room(self):
        """EntityDroppedEvent uses the entity's target room."""
        changed: list[str] = []
        observer = EntityMutationObserver(
            room_id="lobby",
            on_room_changed=changed.append,
            on_rebuild=lambda _: None,
        )
        entity = _make_instance("Sword")
        dropped = replace(entity, room_id="garden", owner_id=None)

        observer.notify(EntityDroppedEvent(instance=dropped))

        assert changed == ["garden"]

    def test_drop_with_no_room_is_ignored(self):
        """EntityDroppedEvent with no room_id is a no-op."""
        changed: list[str] = []
        observer = EntityMutationObserver(
            room_id="lobby",
            on_room_changed=changed.append,
            on_rebuild=lambda _: None,
        )
        entity = _make_instance("Sword")
        dropped = replace(entity, room_id=None, owner_id=None)

        observer.notify(EntityDroppedEvent(instance=dropped))

        assert changed == []

    def test_destroy_uses_entity_room(self):
        """EntityDestroyedEvent uses the entity's room."""
        changed: list[str] = []
        observer = EntityMutationObserver(
            room_id="lobby",
            on_room_changed=changed.append,
            on_rebuild=lambda _: None,
        )
        entity = _make_instance("Sword")
        destroyed = replace(entity, room_id="garden")

        observer.notify(EntityDestroyedEvent(instance=destroyed))

        assert changed == ["garden"]

    def test_destroy_falls_back_to_scene_room(self):
        """EntityDestroyedEvent falls back to scene room when entity has no room."""
        changed: list[str] = []
        observer = EntityMutationObserver(
            room_id="lobby",
            on_room_changed=changed.append,
            on_rebuild=lambda _: None,
        )
        entity = _make_instance("Sword")
        destroyed = replace(entity, room_id=None)

        observer.notify(EntityDestroyedEvent(instance=destroyed))

        assert changed == ["lobby"]

    def test_unrelated_event_is_ignored(self):
        """Events that aren't entity mutations are ignored."""
        changed: list[str] = []
        observer = EntityMutationObserver(
            room_id="lobby",
            on_room_changed=changed.append,
            on_rebuild=lambda _: None,
        )
        # Use a non-entity event — any GameEvent that doesn't match
        from mudd.events import UserMovedEvent

        observer.notify(
            UserMovedEvent(user_id=1, from_room="a", to_room="b", guild_id=1)
        )

        assert changed == []


class TestFlush:
    """Tests for EntityMutationObserver.flush()."""

    @pytest.mark.asyncio
    async def test_flush_calls_rebuild_for_affected_rooms(self):
        """flush() calls on_rebuild for each affected room."""
        rebuilt: list[str] = []

        async def on_rebuild(room_id: str) -> None:
            rebuilt.append(room_id)

        observer = EntityMutationObserver(
            room_id="lobby",
            on_room_changed=lambda _: None,
            on_rebuild=on_rebuild,
        )
        entity = _make_instance("Sword")
        picked_up = replace(entity, room_id=None, owner_id=12345)
        observer.notify(EntityPickedUpEvent(instance=picked_up))

        await observer.flush()

        assert rebuilt == ["lobby"]

    @pytest.mark.asyncio
    async def test_flush_clears_affected_rooms(self):
        """flush() clears the affected rooms set."""

        async def on_rebuild(room_id: str) -> None:
            pass

        observer = EntityMutationObserver(
            room_id="lobby",
            on_room_changed=lambda _: None,
            on_rebuild=on_rebuild,
        )
        entity = _make_instance("Sword")
        picked_up = replace(entity, room_id=None, owner_id=12345)
        observer.notify(EntityPickedUpEvent(instance=picked_up))

        await observer.flush()

        assert observer._affected_rooms == set()

    @pytest.mark.asyncio
    async def test_flush_deduplicates_rooms(self):
        """Multiple events for the same room only trigger one rebuild."""
        rebuilt: list[str] = []

        async def on_rebuild(room_id: str) -> None:
            rebuilt.append(room_id)

        observer = EntityMutationObserver(
            room_id="lobby",
            on_room_changed=lambda _: None,
            on_rebuild=on_rebuild,
        )
        # Two pickups from the same room
        for _ in range(2):
            entity = _make_instance("Sword")
            picked_up = replace(entity, room_id=None, owner_id=12345)
            observer.notify(EntityPickedUpEvent(instance=picked_up))

        await observer.flush()

        assert rebuilt == ["lobby"]
