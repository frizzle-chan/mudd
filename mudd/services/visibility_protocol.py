"""Protocol defining the VisibilityService interface."""

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import discord


class VisibilityServiceProtocol(Protocol):
    """Interface for visibility/location management services.

    Real implementation: VisibilityService (requires Discord guild)
    Test implementation: StubVisibilityService (no Discord required)
    """

    @property
    def startup_complete(self) -> bool:
        """Check if startup sync has completed (non-blocking)."""
        ...

    @property
    def default_room(self) -> str:
        """Get the default room name."""
        ...

    async def wait_for_startup(self) -> None:
        """Block until startup sync is complete."""
        ...

    def mark_startup_complete(self) -> None:
        """Signal that initial startup sync is complete."""
        ...

    def get_default_channel_id(self) -> int | None:
        """Get the default room's channel ID."""
        ...

    async def get_user_location(self, user_id: int) -> int | None:
        """Get the channel ID of the user's current location, or None if not set."""
        ...

    async def delete_user_location(self, user_id: int) -> None:
        """Remove user's location assignment from the database."""
        ...

    async def move_user_to_channel(
        self, member: "discord.Member", channel_id: int
    ) -> bool:
        """Move user to a new location.

        Returns True if moved, False if already there.
        """
        ...

    async def get_room_name(self, room_id: str) -> str | None:
        """Get the display name for a room ID."""
        ...

    async def sync_guild(self, guild: "discord.Guild") -> dict[str, int]:
        """Synchronize all users' Discord permissions to match database state."""
        ...
