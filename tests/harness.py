"""Test harness for command-based testing.

Provides a TestClient that wires up cogs with test services and allows
executing commands in sequence without patching.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

import asyncpg
import discord

from mudd.cogs.economy import Economy
from mudd.cogs.interact import Interact
from mudd.cogs.look import Look
from mudd.cogs.movement import Movement
from mudd.services.currency import CurrencyService
from mudd.services.entity import EntityService
from mudd.services.entity_resolution import EntityResolutionService
from mudd.services.focus_context import FocusContextService
from mudd.services.inventory import InventoryService
from mudd.services.rendering import RenderingService
from tests.mocks.discord import (
    MockGuild,
    MockInteraction,
    MockMember,
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
        self._stub_visibility_service = StubVisibilityService()
        self.rendering_service = RenderingService()
        self.inventory_service = InventoryService(pool, self.entity_service)
        self.currency_service = CurrencyService(pool)
        self.entity_resolution = EntityResolutionService(
            self.entity_service, self.focus_service, self.inventory_service, pool
        )

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
            entity_resolution=self.entity_resolution,
            visibility_service=visibility_service,
            rendering_service=self.rendering_service,
            inventory_service=self.inventory_service,
            currency_service=self.currency_service,
            pool=pool,
        )
        self.interact_cog = Interact(
            bot=None,
            entity_service=self.entity_service,
            entity_resolution=self.entity_resolution,
            visibility_service=visibility_service,
            inventory_service=self.inventory_service,
            pool=pool,
            rendering_service=self.rendering_service,
            currency_service=self.currency_service,
        )
        self.movement_cog = Movement(
            bot=None,
            visibility_service=visibility_service,
            entity_resolution=self.entity_resolution,
            inventory_service=self.inventory_service,
        )
        self.economy_cog = Economy(
            bot=None,
            currency_service=self.currency_service,
            visibility_service=visibility_service,
            inventory_service=self.inventory_service,
            entity_service=self.entity_service,
            rendering_service=self.rendering_service,
            pool=pool,
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
        # Set room in visibility stub for same-room checks
        self._stub_visibility_service.set_user_room(user_id, room)
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
        guild = await self._build_mock_guild()
        interaction = MockInteraction(user.id, user.room, topic, guild=guild)
        await self.interact_cog.interact.callback(
            self.interact_cog, interaction, action=action, target=target
        )
        return interaction.last_response

    async def interact_with_broadcasts(
        self, user: TestUser, action: str, target: str
    ) -> tuple[str, list[str]]:
        """Execute /interact command and return both ephemeral and broadcast messages.

        Args:
            user: The test user executing the command.
            action: The verb action (e.g., "open", "touch", "smash").
            target: The entity name to interact with.

        Returns:
            Tuple of (ephemeral response, list of broadcast messages).
        """
        topic = await self._get_room_topic(user.room)
        guild = await self._build_mock_guild()
        interaction = MockInteraction(user.id, user.room, topic, guild=guild)

        # Clear any previous sent messages on the channel (MockTextChannel)
        channel = cast(MockTextChannel, interaction.channel)
        channel.sent_messages.clear()

        await self.interact_cog.interact.callback(
            self.interact_cog, interaction, action=action, target=target
        )

        broadcasts = channel.sent_messages.copy()

        return interaction.last_response, broadcasts

    async def get_focus(self, user: TestUser) -> dict | None:
        """Get the user's current focus state from database.

        Joins with entity_instances to include entity_id and room,
        which were previously stored directly in user_focus.

        Returns:
            Focus data as dict with user_id, instance_id, entity_id, room,
            updated_at, or None if no focus.
        """
        row = await self.pool.fetchrow(
            """
            SELECT uf.user_id, uf.instance_id, uf.updated_at,
                   ei.entity_id, ei.room
            FROM user_focus uf
            JOIN entity_instances ei ON ei.id = uf.instance_id
            WHERE uf.user_id = $1
            """,
            user.id,
        )
        return dict(row) if row else None

    async def add_guild_member(
        self, user_id: int, display_name: str | None = None, bot: bool = False
    ) -> None:
        """Add a member to the mock guild.

        This is useful for testing scenarios involving bot users or
        customizing member display names.

        Args:
            user_id: Discord user ID
            display_name: Optional custom display name
            bot: Whether this is a bot user
        """
        guild = await self._build_mock_guild()
        member = MockMember(user_id, display_name, bot)
        guild.add_member(member)

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

    async def get_inventory(self, user: TestUser) -> list[tuple[str, str]]:
        """Get items in user's inventory.

        Args:
            user: The test user whose inventory to check.

        Returns:
            List of (entity_id, entity_name) tuples.
        """
        instances = await self.entity_service.get_user_inventory(user.id)
        return [(inst.entity.id, inst.entity.name) for inst in instances]

    async def is_entity_in_room(self, entity_id: str, room: str) -> bool:
        """Check if an entity instance exists in a room.

        Args:
            entity_id: The entity ID to check for.
            room: The room ID to search in.

        Returns:
            True if the entity has an instance in the room.
        """
        row = await self.pool.fetchrow(
            "SELECT id FROM entity_instances WHERE entity_id = $1 AND room = $2",
            entity_id,
            room,
        )
        return row is not None

    async def count_player_dropped_items(self, room: str) -> int:
        """Count player-dropped items in a room.

        Args:
            room: The room ID to count dropped items in.

        Returns:
            Number of player-dropped items in the room.
        """
        count = await self.pool.fetchval(
            """SELECT COUNT(*) FROM entity_instances
            WHERE room = $1 AND player_dropped = TRUE""",
            room,
        )
        return count or 0

    async def count_floor_dropped_items(self, room: str) -> int:
        """Count player-dropped items on the floor (not in containers).

        Args:
            room: The room ID to count floor items in.

        Returns:
            Number of player-dropped items on the floor (not in containers).
        """
        count = await self.pool.fetchval(
            """SELECT COUNT(*) FROM entity_instances
            WHERE room = $1 AND player_dropped = TRUE
            AND container_entity_id IS NULL""",
            room,
        )
        return count or 0

    async def is_entity_in_container(
        self, entity_id: str, container_id: str, room: str
    ) -> bool:
        """Check if entity instance is inside a container.

        Args:
            entity_id: The entity ID to check for.
            container_id: The container entity ID.
            room: The room ID where the container is.

        Returns:
            True if the entity has an instance inside the container.
        """
        row = await self.pool.fetchrow(
            """SELECT id FROM entity_instances
            WHERE entity_id = $1 AND container_entity_id = $2 AND room = $3""",
            entity_id,
            container_id,
            room,
        )
        return row is not None

    async def spawn_from_pool(self, pool_id: str) -> str | None:
        """Spawn an entity from a spawning pool.

        Creates an entity instance from the specified spawning pool,
        bypassing the normal respawn timer. Used for testing entities
        that spawn via pools rather than world instances.

        Args:
            pool_id: The spawning pool ID to spawn from.

        Returns:
            The entity_id of the spawned entity, or None if spawn failed.
        """
        # Get pool configuration
        pool_config = await self.pool.fetchrow(
            """SELECT room, container_id, tag_query
            FROM spawning_pools WHERE id = $1""",
            pool_id,
        )
        if pool_config is None:
            return None

        # Get a random entity matching the tag (using weighted rarity)
        entity = await self.entity_service.get_random_entity_by_tag(
            pool_config["tag_query"]
        )
        if entity is None:
            return None

        # Create the instance
        await self.pool.execute(
            """INSERT INTO entity_instances
                (entity_id, room, spawning_pool_id, container_entity_id)
            VALUES ($1, $2, $3, $4)""",
            entity.id,
            pool_config["room"],
            pool_id,
            pool_config["container_id"],
        )

        # Invalidate cache
        self.entity_service.invalidate_cache()

        return entity.id

    def _setup_user_channel_location(self, user_id: int, guild: MockGuild) -> None:
        """Set up user's channel location from their room for same-room checks.

        Uses the stub's room data (set by create_user) to find the matching
        channel and set the channel location.

        Args:
            user_id: The user's ID.
            guild: The mock guild.
        """
        room = self._stub_visibility_service._user_rooms.get(user_id)
        if room:
            channel = next((ch for ch in guild.text_channels if ch.name == room), None)
            if channel:
                self._stub_visibility_service.set_user_location(user_id, channel.id)

    def _ensure_guild_member(self, user_id: int, guild: MockGuild) -> None:
        """Ensure a user is in the guild's member list.

        Args:
            user_id: The user's ID.
            guild: The mock guild.
        """
        if user_id not in guild._members:
            guild.add_member(MockMember(user_id))

    async def pay(self, user: TestUser, recipient: str, amount: int) -> str:
        """Execute /pay command.

        Args:
            user: The test user executing the command.
            recipient: The recipient user ID (as string).
            amount: Amount to pay in yen.

        Returns:
            The response message from the command.
        """
        guild = await self._build_mock_guild()
        topic = await self._get_room_topic(user.room)

        # Create a mock member that passes isinstance(member, discord.Member)
        mock_member = MagicMock(spec=discord.Member)
        mock_member.id = user.id
        mock_member.display_name = f"TestUser{user.id}"

        interaction = MockInteraction(user.id, user.room, topic, guild=guild)
        interaction.user = mock_member

        # Set up channel locations for same-room check
        self._setup_user_channel_location(user.id, guild)
        try:
            recipient_id = int(recipient)
            self._setup_user_channel_location(recipient_id, guild)
            self._ensure_guild_member(recipient_id, guild)
        except (ValueError, TypeError):
            pass  # Invalid recipient ID - let the command handle it

        await self.economy_cog.pay.callback(
            self.economy_cog, interaction, recipient=recipient, amount=amount
        )
        return interaction.last_response

    async def recipient_autocomplete(
        self, user: TestUser, current: str = ""
    ) -> list[AutocompleteResult]:
        """Get autocomplete suggestions for /pay recipient: parameter.

        Args:
            user: The test user executing the autocomplete.
            current: The current input text for filtering.

        Returns:
            List of autocomplete suggestions.
        """
        guild = await self._build_mock_guild()
        topic = await self._get_room_topic(user.room)

        # Create a mock member that passes isinstance(member, discord.Member)
        mock_member = MagicMock(spec=discord.Member)
        mock_member.id = user.id
        mock_member.display_name = f"TestUser{user.id}"

        mock_interaction = MockInteraction(user.id, user.room, topic, guild=guild)
        mock_interaction.user = mock_member

        # Cast for type checker (MockInteraction provides needed interface)
        interaction = cast("Interaction[Any]", mock_interaction)
        choices = await self.economy_cog.recipient_autocomplete(interaction, current)
        return [AutocompleteResult(name=c.name, value=c.value) for c in choices]
