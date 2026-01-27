"""Discord mock factories for integration tests.

Only mock Discord API objects - all other services should use real
database connections in integration tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import asyncpg
import discord

if TYPE_CHECKING:
    pass


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


class MockTextChannel(discord.TextChannel):
    """Mock Discord text channel with ID for movement testing.

    Inherits from discord.TextChannel so it passes isinstance() checks,
    but doesn't call super().__init__() since we're a test mock.
    """

    def __init__(
        self, name: str, topic: str | None = None, channel_id: int | None = None
    ) -> None:
        # Don't call super().__init__() - we're a test mock
        self.name = name
        self.topic = topic
        # Use hash of name as default ID to ensure consistency
        self.id = channel_id if channel_id is not None else hash(name) & 0xFFFFFFFF
        # Capture messages sent to channel (for testing broadcasts)
        self.sent_messages: list[str] = []

    @property
    def mention(self) -> str:
        """Return Discord-style channel mention."""
        return f"<#{self.id}>"

    async def send(self, content: str, **kwargs) -> None:  # type: ignore[override]
        """Capture messages sent to the channel."""
        self.sent_messages.append(content)


class MockMember(discord.Member):
    """Mock Discord member for testing.

    Inherits from discord.Member so it passes isinstance() checks,
    but doesn't call super().__init__() since we're a test mock.
    """

    def __init__(
        self, user_id: int, display_name: str | None = None, bot: bool = False
    ) -> None:
        # Don't call super().__init__() - we're a test mock
        self.id = user_id
        self.name = f"testuser{user_id}"  # Discord username (lowercased)
        self._display_name = display_name or f"TestUser{user_id}"
        self.bot = bot

    @property
    def display_name(self) -> str:
        """Return Discord-style display name."""
        return self._display_name

    @property
    def mention(self) -> str:
        """Return Discord-style user mention."""
        return f"<@{self.id}>"


class MockForumChannel:
    """Mock Discord forum channel for inventory testing."""

    def __init__(
        self, name: str, forum_id: int | None = None, category_id: int | None = None
    ) -> None:
        self.name = name
        self.id = forum_id if forum_id is not None else hash(name) & 0xFFFFFFFF
        self.category_id = category_id
        self._threads: dict[int, MockThread] = {}
        self._next_thread_id = 1

    async def create_thread(
        self, *, name: str, content: str
    ) -> tuple[MockThread, MockMessage]:
        """Create a thread in the forum."""
        thread_id = self._next_thread_id
        self._next_thread_id += 1
        thread = MockThread(name, thread_id, self)
        message = MockMessage(content)
        self._threads[thread_id] = thread
        return thread, message

    async def edit(self, *, name: str | None = None, **kwargs) -> None:
        """Edit forum properties."""
        if name is not None:
            self.name = name

    def set_permissions(self, member: MockMember, **kwargs) -> None:
        """Mock permission setting (no-op for tests)."""
        pass

    def overwrites_for(self, member: MockMember) -> MockPermissionOverwrite:
        """Get permission overwrites for a member."""
        return MockPermissionOverwrite()


class MockThread:
    """Mock Discord thread for inventory testing."""

    def __init__(
        self, name: str, thread_id: int, parent: MockForumChannel | None = None
    ) -> None:
        self.name = name
        self.id = thread_id
        self.parent = parent

    async def delete(self) -> None:
        """Delete the thread."""
        if self.parent and self.id in self.parent._threads:
            del self.parent._threads[self.id]


class MockMessage:
    """Mock Discord message."""

    _next_id = 1

    def __init__(self, content: str) -> None:
        self.content = content
        self.id = MockMessage._next_id
        MockMessage._next_id += 1


class MockCategoryChannel:
    """Mock Discord category channel for inventory testing."""

    def __init__(self, name: str, category_id: int | None = None) -> None:
        self.name = name
        self.id = category_id if category_id is not None else hash(name) & 0xFFFFFFFF
        self._forums: dict[int, MockForumChannel] = {}
        self._next_forum_id = 1

    @property
    def channels(self) -> list[MockForumChannel]:
        """Return all channels (forums) in this category."""
        return list(self._forums.values())

    async def create_forum(
        self, name: str, *, topic: str = "", overwrites: dict | None = None
    ) -> MockForumChannel:
        """Create a forum in this category."""
        forum_id = self._next_forum_id
        self._next_forum_id += 1
        forum = MockForumChannel(name, forum_id, category_id=self.id)
        self._forums[forum_id] = forum
        return forum


class MockPermissionOverwrite:
    """Mock Discord permission overwrite."""

    def __init__(self) -> None:
        self.create_public_threads: bool | None = None


class MockRole:
    """Mock Discord role."""

    def __init__(self, role_id: int = 0) -> None:
        self.id = role_id


class MockGuild:
    """Mock Discord guild with text channels for movement testing."""

    def __init__(self, channels: list[MockTextChannel] | None = None) -> None:
        self.id = hash("mock_guild") & 0xFFFFFFFF
        self._channels = channels or []
        self._channel_by_id: dict[int, MockTextChannel] = {
            ch.id: ch for ch in self._channels
        }
        self._members: dict[int, MockMember] = {}
        self._categories: list[MockCategoryChannel] = []
        self._threads: dict[int, MockThread] = {}
        self.default_role = MockRole()
        self.name = "Test Guild"

    @property
    def text_channels(self) -> list[MockTextChannel]:
        return self._channels

    @property
    def categories(self) -> list[MockCategoryChannel]:
        return self._categories

    @property
    def forums(self) -> list[MockForumChannel]:
        """Return all forum channels across all categories."""
        all_forums: list[MockForumChannel] = []
        for category in self._categories:
            all_forums.extend(category._forums.values())
        return all_forums

    def get_channel(
        self, channel_id: int
    ) -> MockTextChannel | MockCategoryChannel | MockForumChannel | None:
        """Get a channel by its ID."""
        if channel_id in self._channel_by_id:
            return self._channel_by_id[channel_id]
        # Check categories
        for category in self._categories:
            if category.id == channel_id:
                return category
            # Check forums in category
            for forum in category._forums.values():
                if forum.id == channel_id:
                    return forum
        return None

    def get_thread(self, thread_id: int) -> MockThread | None:
        """Get a thread by its ID."""
        # Check threads in all forums in all categories
        for category in self._categories:
            for forum in category._forums.values():
                if thread_id in forum._threads:
                    return forum._threads[thread_id]
        return self._threads.get(thread_id)

    async def create_category(
        self, name: str, *, overwrites: dict | None = None
    ) -> MockCategoryChannel:
        """Create a category channel."""
        category = MockCategoryChannel(name)
        self._categories.append(category)
        return category

    def add_channel(self, channel: MockTextChannel) -> None:
        """Add a channel to the guild."""
        self._channels.append(channel)
        self._channel_by_id[channel.id] = channel

    def get_member(self, user_id: int) -> MockMember | None:
        """Get a member by their ID, creating if needed for tests."""
        if user_id not in self._members:
            # Auto-create members for test convenience
            self._members[user_id] = MockMember(user_id)
        return self._members[user_id]

    async def fetch_member(self, user_id: int) -> MockMember | None:
        """Fetch a member (same as get_member for tests)."""
        return self.get_member(user_id)

    def add_member(self, member: MockMember) -> None:
        """Add a member to the guild."""
        self._members[member.id] = member


class MockUser:
    """Mock Discord user."""

    def __init__(self, user_id: int, display_name: str | None = None) -> None:
        self.id = user_id
        self.display_name = display_name or f"TestUser{user_id}"

    @property
    def mention(self) -> str:
        """Return Discord-style user mention."""
        return f"<@{self.id}>"


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

    def __init__(
        self, default_room: str = "foyer", pool: asyncpg.Pool | None = None
    ) -> None:
        self._startup_complete = True  # Tests start ready
        self._default_room = default_room
        self._room_names: dict[str, str] = {}
        self._user_locations: dict[int, int] = {}
        self._pool = pool

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

    async def get_user_room(self, user_id: int) -> str | None:
        """Get the room name of the user's current location."""
        # If we have a database pool, use it like the real service
        if self._pool:
            row = await self._pool.fetchrow(
                "SELECT current_room FROM users WHERE id = $1",
                user_id,
            )
            return row["current_room"] if row else None
        # Otherwise, return None
        return None

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


def make_stub_visibility_service(
    default_room: str = "foyer", pool: asyncpg.Pool | None = None
) -> StubVisibilityService:
    """Create a StubVisibilityService for tests.

    Args:
        default_room: The default room name.
        pool: Optional database pool for get_user_room queries.

    Returns:
        StubVisibilityService instance.
    """
    return StubVisibilityService(default_room, pool)


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
