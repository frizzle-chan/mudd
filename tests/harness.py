"""Test harness for command-based testing.

Provides a TestClient that wires up cogs with test services and allows
executing commands in sequence without patching.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

import asyncpg
import discord

from mudd.cogs.interact import Interact
from mudd.cogs.look import Look
from mudd.cogs.movement import Movement
from mudd.services.entity import EntityService
from mudd.services.focus_context import FocusContextService
from mudd.services.inventory import InventoryService
from mudd.services.player_context import PlayerContextService
from mudd.services.rendering import RenderingService
from tests.mocks.discord import (
    MockGuild,
    MockInteraction,
    MockTextChannel,
    StubVisibilityService,
)

if TYPE_CHECKING:
    from discord import Interaction

    from mudd.services.visibility import VisibilityServiceProtocol


@dataclass
class AutocompleteResult:
    """Result from an autocomplete method."""

    name: str  # Display name (what user sees)
    value: str  # Value sent to command


class TestUser:
    """Tracks a test user's state (current room).

    The TestUser automatically tracks which room the user is in,
    so tests don't need to manually track state.
    """

    def __init__(self, user_id: int, starting_room: str = "foyer") -> None:
        self.id = user_id
        self.room = starting_room


class TestClient:
    """Test client that wires up cogs with test services.

    Creates real services connected to the test database, with only
    Discord API objects mocked.

    Usage:
        async def test_workflow(test_db):
            client = TestClient(test_db)
            user = await client.create_user(user_id=123)

            # Execute commands in sequence
            response = await client.look(user)
            assert "grand entryway" in response

            response = await client.interact(user, "open", "Wooden Chest")
            assert "open" in response.lower()
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

        # Create real services with test database
        self.entity_service = EntityService(pool)
        self.focus_service = FocusContextService(pool)
        self.player_context = PlayerContextService(
            self.entity_service, self.focus_service
        )
        self._stub_visibility_service = StubVisibilityService()
        self.rendering_service = RenderingService()
        self.inventory_service = InventoryService(pool, self.entity_service)

        # Cast stub to VisibilityServiceProtocol for type checking
        # (StubVisibilityService implements the protocol interface)
        visibility_service = cast(
            "VisibilityServiceProtocol", self._stub_visibility_service
        )
        self._visibility_service = visibility_service

        # Create cogs with injected services
        self.look_cog = Look(
            bot=None,
            entity_service=self.entity_service,
            player_context=self.player_context,
            visibility_service=visibility_service,
            rendering_service=self.rendering_service,
        )
        self.interact_cog = Interact(
            bot=None,
            entity_service=self.entity_service,
            player_context=self.player_context,
            visibility_service=visibility_service,
            pool=pool,
            rendering_service=self.rendering_service,
        )
        self.movement_cog = Movement(
            bot=None,
            visibility_service=visibility_service,
            player_context=self.player_context,
            inventory_service=self.inventory_service,
        )

        # Cached mock guild (built lazily from DB room data)
        self._mock_guild: MockGuild | None = None

    async def create_user(self, user_id: int, room: str = "foyer") -> TestUser:
        """Create a test user starting in the given room.

        Inserts the user into the database and returns a TestUser
        object that tracks their state.
        """
        await self.pool.execute(
            """
            INSERT INTO users (id, current_room)
            VALUES ($1, $2)
            ON CONFLICT (id) DO UPDATE SET current_room = $2
            """,
            user_id,
            room,
        )
        return TestUser(user_id, room)

    async def _get_room_topic(self, room: str) -> str | None:
        """Get the room's description (topic) from database."""
        row = await self.pool.fetchrow(
            "SELECT description FROM rooms WHERE id = $1", room
        )
        return row["description"] if row else None

    async def look(self, user: TestUser, at: str = "Room") -> str:
        """Execute /look command in user's current room.

        Args:
            user: The test user executing the command.
            at: What to look at ("Room" for room description, or entity name).

        Returns:
            The response message from the command.
        """
        topic = await self._get_room_topic(user.room)
        interaction = MockInteraction(user.id, user.room, topic)
        await self.look_cog.look.callback(self.look_cog, interaction, at=at)
        return interaction.last_response

    async def interact(self, user: TestUser, action: str, target: str) -> str:
        """Execute /interact command in user's current room.

        Args:
            user: The test user executing the command.
            action: The verb action (e.g., "open", "touch", "smash").
            target: The entity name to interact with.

        Returns:
            The response message from the command.
        """
        topic = await self._get_room_topic(user.room)
        interaction = MockInteraction(user.id, user.room, topic)
        await self.interact_cog.interact.callback(
            self.interact_cog, interaction, action=action, target=target
        )
        return interaction.last_response

    async def get_focus(self, user: TestUser) -> dict | None:
        """Get the user's current focus state from database.

        Returns:
            Focus row as dict, or None if no focus.
        """
        row = await self.pool.fetchrow(
            "SELECT * FROM user_focus WHERE user_id = $1", user.id
        )
        return dict(row) if row else None

    async def _build_mock_guild(self) -> MockGuild:
        """Build MockGuild from database room data.

        Caches the result to avoid repeated database queries.
        """
        if self._mock_guild is not None:
            return self._mock_guild

        rows = await self.pool.fetch("SELECT id, description FROM rooms")
        channels = [
            MockTextChannel(name=row["id"], topic=row["description"]) for row in rows
        ]
        self._mock_guild = MockGuild(channels)
        return self._mock_guild

    async def look_autocomplete(
        self, user: TestUser, current: str = ""
    ) -> list[AutocompleteResult]:
        """Get autocomplete suggestions for /look at: parameter.

        Args:
            user: The test user executing the autocomplete.
            current: The current input text for filtering.

        Returns:
            List of autocomplete suggestions.
        """
        topic = await self._get_room_topic(user.room)
        mock_interaction = MockInteraction(user.id, user.room, topic)
        # Cast for type checker (MockInteraction provides needed interface)
        interaction = cast("Interaction[Any]", mock_interaction)
        choices = await self.look_cog.at_autocomplete(interaction, current)
        return [AutocompleteResult(name=c.name, value=c.value) for c in choices]

    async def interact_autocomplete(
        self, user: TestUser, current: str = ""
    ) -> list[AutocompleteResult]:
        """Get autocomplete suggestions for /interact target: parameter.

        Args:
            user: The test user executing the autocomplete.
            current: The current input text for filtering.

        Returns:
            List of autocomplete suggestions.
        """
        topic = await self._get_room_topic(user.room)
        mock_interaction = MockInteraction(user.id, user.room, topic)
        # Cast for type checker (MockInteraction provides needed interface)
        interaction = cast("Interaction[Any]", mock_interaction)
        choices = await self.interact_cog.target_autocomplete(interaction, current)
        return [AutocompleteResult(name=c.name, value=c.value) for c in choices]

    async def move_autocomplete(
        self, user: TestUser, current: str = ""
    ) -> list[AutocompleteResult]:
        """Get autocomplete suggestions for /move destination: parameter.

        Args:
            user: The test user executing the autocomplete.
            current: The current input text for filtering.

        Returns:
            List of autocomplete suggestions.
        """
        guild = await self._build_mock_guild()
        topic = await self._get_room_topic(user.room)
        mock_interaction = MockInteraction(user.id, user.room, topic, guild=guild)
        # Cast for type checker (MockInteraction provides needed interface)
        interaction = cast("Interaction[Any]", mock_interaction)
        choices = await self.movement_cog.destination_autocomplete(interaction, current)
        return [AutocompleteResult(name=c.name, value=c.value) for c in choices]

    async def move(self, user: TestUser, destination: str) -> str:
        """Execute /move command.

        Args:
            user: The test user executing the command.
            destination: The destination room name.

        Returns:
            The response message from the command.
        """
        guild = await self._build_mock_guild()
        topic = await self._get_room_topic(user.room)
        interaction = MockInteraction(user.id, user.room, topic, guild=guild)

        # Create a mock member that passes isinstance(member, discord.Member)
        mock_member = MagicMock(spec=discord.Member)
        mock_member.id = user.id
        mock_member.display_name = f"TestUser{user.id}"
        interaction.user = mock_member

        # Set up user location in visibility service for movement tracking
        current_channel = next(
            (ch for ch in guild.text_channels if ch.name == user.room), None
        )
        if current_channel:
            self._stub_visibility_service.set_user_location(user.id, current_channel.id)

        await self.movement_cog.move.callback(
            self.movement_cog, interaction, destination=destination
        )

        # Update user's room if movement was successful
        if "You moved!" in interaction.last_response:
            user.room = destination
            # Update database to match
            await self.pool.execute(
                "UPDATE users SET current_room = $1 WHERE id = $2",
                destination,
                user.id,
            )

        return interaction.last_response
