"""Discord mock factories for integration tests.

Only mock Discord API objects - all other services should use real
database connections in integration tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock


class MockResponse:
    """Captures response messages sent via interaction.response.send_message."""

    def __init__(self) -> None:
        self.messages: list[str] = []
        self._deferred = False

    async def send_message(
        self, content: str, *, ephemeral: bool = False, **kwargs
    ) -> None:
        """Capture the message content."""
        self.messages.append(content)

    async def defer(self, *, ephemeral: bool = False) -> None:
        """Mock defer for long operations."""
        self._deferred = True

    def is_done(self) -> bool:
        """Check if a response has been sent."""
        return len(self.messages) > 0 or self._deferred


class MockChannel:
    """Mock Discord channel (legacy, for backward compatibility)."""

    def __init__(self, name: str, topic: str | None = None) -> None:
        self.name = name
        self.topic = topic


class MockTextChannel:
    """Mock Discord text channel with ID for movement testing."""

    def __init__(
        self, name: str, topic: str | None = None, channel_id: int | None = None
    ) -> None:
        self.name = name
        self.topic = topic
        # Use hash of name as default ID to ensure consistency
        self.id = channel_id if channel_id is not None else hash(name) & 0xFFFFFFFF

    @property
    def mention(self) -> str:
        """Return Discord-style channel mention."""
        return f"<#{self.id}>"

    async def send(self, content: str) -> None:
        """Mock sending a message to the channel (no-op in tests)."""
        pass


class MockGuild:
    """Mock Discord guild with text channels for movement testing."""

    def __init__(self, channels: list[MockTextChannel] | None = None) -> None:
        self._channels = channels or []
        self._channel_by_id: dict[int, MockTextChannel] = {
            ch.id: ch for ch in self._channels
        }

    @property
    def text_channels(self) -> list[MockTextChannel]:
        return self._channels

    def get_channel(self, channel_id: int) -> MockTextChannel | None:
        """Get a channel by its ID."""
        return self._channel_by_id.get(channel_id)

    def add_channel(self, channel: MockTextChannel) -> None:
        """Add a channel to the guild."""
        self._channels.append(channel)
        self._channel_by_id[channel.id] = channel


class MockUser:
    """Mock Discord user."""

    def __init__(self, user_id: int) -> None:
        self.id = user_id


class MockInteraction:
    """Mock Discord interaction that captures responses.

    Usage in tests:
        interaction = MockInteraction(user_id=123, room="foyer", topic="A grand foyer.")
        await cog.look.callback(cog, interaction, at="Room")
        assert "grand" in interaction.last_response
    """

    def __init__(
        self,
        user_id: int,
        room: str,
        topic: str | None = "A room.",
        guild: MockGuild | None = None,
    ) -> None:
        self.user = MockUser(user_id)
        self.response = MockResponse()
        self.guild = guild

        # Use MockTextChannel if guild is provided (for movement tests)
        if guild:
            # Find existing channel in guild or create one
            channel = next((ch for ch in guild.text_channels if ch.name == room), None)
            if channel is None:
                channel = MockTextChannel(room, topic)
                guild.add_channel(channel)
            self.channel: MockChannel | MockTextChannel = channel
        else:
            self.channel = MockChannel(room, topic)

    @property
    def last_response(self) -> str:
        """Get the last response message, or empty string if none."""
        if self.response.messages:
            return self.response.messages[-1]
        return ""

    @property
    def all_responses(self) -> list[str]:
        """Get all response messages."""
        return self.response.messages


class StubVisibilityService:
    """Test stub implementing VisibilityServiceProtocol.

    Provides in-memory implementation for tests without Discord.
    The VisibilityService manages Discord permissions and is tightly
    coupled to Discord API - we use this stub in tests.
    """

    def __init__(self, default_room: str = "foyer") -> None:
        self._startup_complete = True  # Tests start ready
        self._default_room = default_room
        self._room_names: dict[str, str] = {}
        self._user_locations: dict[int, int] = {}

    @property
    def startup_complete(self) -> bool:
        """Check if startup sync has completed."""
        return self._startup_complete

    async def wait_for_startup(self) -> None:
        """No-op for tests - immediately returns."""
        pass

    def mark_startup_complete(self) -> None:
        """Mark startup as complete."""
        self._startup_complete = True

    async def get_default_room(self) -> str:
        """Get the default room name."""
        return self._default_room

    async def get_default_channel_id(self) -> int | None:
        """Get the default room's channel ID."""
        return None  # Tests don't use real channel IDs

    async def get_user_location(self, user_id: int) -> int | None:
        """Get the channel ID of the user's current location."""
        return self._user_locations.get(user_id)

    async def delete_user_location(self, user_id: int) -> None:
        """Remove user's location assignment."""
        self._user_locations.pop(user_id, None)

    async def move_user_to_channel(self, member, channel_id: int) -> bool:
        """Move user to a new location."""
        current = self._user_locations.get(member.id)
        if current == channel_id:
            return False
        self._user_locations[member.id] = channel_id
        return True

    async def get_room_name(self, room_id: str | None) -> str | None:
        """Return a display name for a room."""
        if room_id is None:
            return None
        return self._room_names.get(room_id)

    async def sync_guild(self, guild) -> dict[str, int]:
        """No-op in tests - returns empty stats."""
        return {}

    # Test helper methods
    def set_room_name(self, room: str, name: str) -> None:
        """Set a display name for testing."""
        self._room_names[room] = name

    def set_user_location(self, user_id: int, channel_id: int) -> None:
        """Set user location directly for testing."""
        self._user_locations[user_id] = channel_id


def make_mock_channel(
    name: str,
    topic: str | None = None,
) -> MagicMock:
    """Create a mock Discord channel (legacy helper).

    Args:
        name: Channel name (corresponds to room ID).
        topic: Channel topic (room description).

    Returns:
        MagicMock mimicking discord.TextChannel.
    """
    channel = MagicMock()
    channel.name = name
    channel.topic = topic
    return channel


def make_mock_interaction(
    user_id: int,
    room: str,
    topic: str | None = "A room.",
) -> MockInteraction:
    """Create a MockInteraction for command testing.

    Args:
        user_id: Discord user ID.
        room: Room name (channel name).
        topic: Room description (channel topic).

    Returns:
        MockInteraction instance.
    """
    return MockInteraction(user_id, room, topic)


def make_stub_visibility_service(default_room: str = "foyer") -> StubVisibilityService:
    """Create a StubVisibilityService for tests.

    Args:
        default_room: The default room name.

    Returns:
        StubVisibilityService instance.
    """
    return StubVisibilityService(default_room)


def make_mock_guild_with_rooms(room_topics: dict[str, str | None]) -> MockGuild:
    """Create MockGuild with channels for each room.

    Args:
        room_topics: Mapping of room names to their topics (descriptions).

    Returns:
        MockGuild with MockTextChannel for each room.
    """
    channels = [
        MockTextChannel(name=room, topic=topic) for room, topic in room_topics.items()
    ]
    return MockGuild(channels)
