"""Scenario-driven integration tests.

Tests read like chat transcripts - each test tells a complete user story
using only commands. No direct database manipulation except for:
- Creating users (required setup)
- Verifying focus state (assertions only)

This replaces component-driven tests organized by feature.
"""

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


class TestUserExploresFoyer:
    """User enters foyer and examines objects."""

    async def test_user_explores_foyer(self, test_client):
        """User looks around the foyer and examines objects."""
        user = await test_client.create_user(user_id=300000001, room="foyer")

        # Autocomplete shows room entities
        results = await test_client.look_autocomplete(user)
        names = [r.name for r in results]
        assert "Room" in names
        assert "Wooden Table" in names

        # Autocomplete filters by prefix
        results = await test_client.interact_autocomplete(user, current="Wood")
        names = [r.name for r in results]
        assert "Wooden Table" in names
        assert "Flower Vase" not in names

        # User looks around the room
        response = await test_client.look(user)
        assert "Wooden Table" in response
        assert "Flower Vase" in response  # visible on table (contents_visible=True)

        # User examines the table
        response = await test_client.look(user, at="Wooden Table")
        assert "sturdy oak" in response.lower() or "worn edges" in response.lower()

        # User examines the vase on the table
        response = await test_client.look(user, at="Flower Vase")
        assert "teal ceramic" in response.lower() or "gold trim" in response.lower()

        # User tries to smash the vase (attack verb)
        response = await test_client.interact(
            user, with_entity="Flower Vase", do_verb="smash"
        )
        assert "intrusive thought" in response.lower()

    async def test_user_touches_table(self, test_client):
        """User touches the table and gets a response."""
        user = await test_client.create_user(user_id=300000002, room="foyer")

        # User touches the table
        response = await test_client.interact(
            user, with_entity="Wooden Table", do_verb="touch"
        )
        assert "touch" in response.lower() or "nothing happens" in response.lower()


class TestUserDiscoversRecords:
    """User finds and explores the record collection in the chest."""

    async def test_user_discovers_records_in_chest(self, test_client):
        """User finds and explores the record collection."""
        user = await test_client.create_user(user_id=300000010, room="library")

        # User looks around - chest is visible but contents are not
        response = await test_client.look(user)
        assert "Wooden Chest" in response
        assert "WLFGRL" not in response  # records hidden (contents_visible=False)

        # Autocomplete doesn't show hidden contents
        results = await test_client.look_autocomplete(user)
        names = [r.name for r in results]
        assert not any("Machine Girl" in name for name in names)

        # User opens the chest - establishes focus
        response = await test_client.interact(
            user, with_entity="Wooden Chest", do_verb="open"
        )
        # Should show contents or "Inside" text
        has_content = any(
            name in response
            for name in ["WLFGRL", "TV Girl", "Clash", "Nujabes", "MGMT", "Inside"]
        )
        assert has_content

        # Focus should now be set
        focus = await test_client.get_focus(user)
        assert focus is not None
        assert focus["entity_id"] == "library_records"

        # Autocomplete now shows chest contents (e.g., "Machine Girl - WLFGRL")
        results = await test_client.look_autocomplete(user)
        names = [r.name for r in results]
        assert any("WLFGRL" in name for name in names)

        # Room option shows close hint when focused
        room_option = next(r for r in results if r.value == "Room")
        assert room_option.name == "[Close Wooden Chest] Room"

        # User examines a record inside the chest
        response = await test_client.look(user, at="WLFGRL")
        assert "Machine Girl" in response

        # Focus preserved when looking at chest contents
        focus = await test_client.get_focus(user)
        assert focus is not None
        assert focus["entity_id"] == "library_records"

    async def test_user_uses_record_from_chest(self, test_client):
        """User opens chest and uses a record."""
        user = await test_client.create_user(user_id=300000011, room="library")

        # User opens the chest
        await test_client.interact(user, with_entity="Wooden Chest", do_verb="open")

        # User uses a record
        response = await test_client.interact(user, with_entity="WLFGRL", do_verb="use")
        assert "music" in response.lower() or "fills the room" in response.lower()

        # Focus preserved when interacting with chest contents
        focus = await test_client.get_focus(user)
        assert focus is not None
        assert focus["entity_id"] == "library_records"


class TestFocusClears:
    """Focus clears when user looks away or closes container."""

    async def test_user_closes_container_explicitly(self, test_client):
        """User opens chest, then closes it explicitly."""
        user = await test_client.create_user(user_id=300000020, room="library")

        # User opens the chest
        await test_client.interact(user, with_entity="Wooden Chest", do_verb="open")

        # Verify focus is set
        focus = await test_client.get_focus(user)
        assert focus is not None

        # User closes the chest
        response = await test_client.interact(
            user, with_entity="Wooden Chest", do_verb="close"
        )
        assert "close" in response.lower()

        # Focus should be cleared
        focus = await test_client.get_focus(user)
        assert focus is None

    async def test_focus_clears_when_looking_at_room(self, test_client):
        """Opening a container then looking at room clears focus."""
        user = await test_client.create_user(user_id=300000021, room="library")

        # User opens the chest
        await test_client.interact(user, with_entity="Wooden Chest", do_verb="open")

        # Verify focus is set
        focus = await test_client.get_focus(user)
        assert focus is not None

        # User looks at room (implicitly closes focus)
        response = await test_client.look(user)

        # Should show on_close content
        assert "close" in response.lower() or "chest" in response.lower()

        # Focus should be cleared
        focus = await test_client.get_focus(user)
        assert focus is None

    async def test_focus_clears_when_looking_at_unrelated_entity(self, test_client):
        """Opening a container then looking elsewhere clears focus."""
        user = await test_client.create_user(user_id=300000022, room="library")

        # User opens the chest
        await test_client.interact(user, with_entity="Wooden Chest", do_verb="open")

        # Verify focus is set
        focus = await test_client.get_focus(user)
        assert focus is not None

        # User looks at bookshelves (not in the chest)
        await test_client.look(user, at="Bookshelves")

        # Focus should be cleared
        focus = await test_client.get_focus(user)
        assert focus is None

    async def test_focus_clears_when_interacting_elsewhere(self, test_client):
        """Opening a container then interacting elsewhere clears focus."""
        user = await test_client.create_user(user_id=300000023, room="library")

        # User opens the chest
        await test_client.interact(user, with_entity="Wooden Chest", do_verb="open")

        # Verify focus is set
        focus = await test_client.get_focus(user)
        assert focus is not None

        # User interacts with bookshelves (not in the chest)
        await test_client.interact(user, with_entity="Bookshelves", do_verb="touch")

        # Focus should be cleared
        focus = await test_client.get_focus(user)
        assert focus is None


class TestEmptyRoom:
    """Tests for rooms with no entities."""

    async def test_empty_room_shows_only_description(self, test_client):
        """Looking at room with no entities shows only room description."""
        user = await test_client.create_user(user_id=300000030, room="hallway")

        response = await test_client.look(user)

        # Should have room description but no entity listing
        assert "hallway" in response.lower() or "nothing special" in response.lower()


class TestInvalidActions:
    """User tries invalid commands and sees helpful messages."""

    async def test_look_at_nonexistent_entity(self, test_client):
        """User tries to look at something that doesn't exist."""
        user = await test_client.create_user(user_id=300000040, room="foyer")

        response = await test_client.look(user, at="Golden Statue")
        assert "don't see" in response.lower()

    async def test_interact_with_nonexistent_entity(self, test_client):
        """User tries to interact with something that doesn't exist."""
        user = await test_client.create_user(user_id=300000041, room="foyer")

        response = await test_client.interact(
            user, with_entity="Nonexistent Thing", do_verb="touch"
        )
        assert "don't see" in response.lower()

    async def test_unknown_verb_shows_error(self, test_client):
        """User tries an unknown verb."""
        user = await test_client.create_user(user_id=300000042, room="foyer")

        response = await test_client.interact(
            user, with_entity="Flower Vase", do_verb="juggle"
        )
        assert "can't do that" in response.lower()


class TestDisambiguation:
    """Tests for disambiguation when multiple entities match."""

    async def test_disambiguation_when_multiple_matches(self, test_client):
        """User searches for partial match that hits multiple entities."""
        user = await test_client.create_user(user_id=300000050, room="library")

        # First open the chest so records are accessible
        await test_client.interact(user, with_entity="Wooden Chest", do_verb="open")

        # Search for partial match "Alvvays" (there are two Alvvays records)
        response = await test_client.look(user, at="Alvvays")

        # Should show disambiguation or match one specific record
        # (fuzzy matching may prefer one, or show "Which one?")
        assert "Alvvays" in response or "Which one?" in response


class TestMovement:
    """Tests for movement commands."""

    async def test_user_moves_between_rooms(self, test_client):
        """User explores the mansion by moving between rooms."""
        user = await test_client.create_user(user_id=400005, room="foyer")

        # User checks available exits via autocomplete
        results = await test_client.move_autocomplete(user)
        values = [r.value for r in results]
        assert "sitting-room" in values
        assert "gallery" in values
        assert "hallway" in values

        # Autocomplete filters by prefix
        results = await test_client.move_autocomplete(user, current="hall")
        assert "hallway" in [r.value for r in results]
        assert "sitting-room" not in [r.value for r in results]

        # User moves to hallway
        response = await test_client.move(user, destination="hallway")
        assert "You moved!" in response
        assert user.room == "hallway"

    async def test_moving_clears_focus(self, test_client):
        """User opens chest then moves - focus should clear."""
        user = await test_client.create_user(user_id=400008, room="library")

        # User opens the chest
        await test_client.interact(user, with_entity="Wooden Chest", do_verb="open")
        focus = await test_client.get_focus(user)
        assert focus is not None

        # User moves to gallery - focus should clear
        await test_client.move(user, destination="gallery")
        focus = await test_client.get_focus(user)
        assert focus is None
