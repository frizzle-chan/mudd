"""View wrappers that format domain objects for user-facing display."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mudd.events import EffectsCollector
from mudd.models import IReadableEntity, IUser
from mudd.utils import async_cached_property
from mudd.utils.text import RARITY_EMOJI


class ViewEntity:
    """View-friendly wrapper for IReadableEntity that formats output for display."""

    def __init__(self, entity: IReadableEntity):
        self._entity = entity

    def __str__(self) -> str:
        """String representation: name with rarity emoji and markdown bold."""
        return self.name

    @property
    def name(self) -> str:
        """Entity name formatted with rarity emoji and markdown bold."""
        return f"**{self.display_name}**"

    @property
    def display_name(self) -> str:
        """Entity name formatted with rarity emoji"""
        emoji = RARITY_EMOJI[self._entity.rarity]
        return f"{self._entity.name} {emoji}" if emoji else self._entity.name

    @property
    def description_long(self) -> str | None:
        """Long description template."""
        return self._entity.description_long

    @property
    def description_short(self) -> str | None:
        """Short description template."""
        return self._entity.description_short

    @async_cached_property
    async def contents(self) -> str:
        """Get contents as a markdown bullet list."""
        contents = await self._entity.get_contents()
        if not contents:
            return ""
        wrapped = [ViewEntity(item) for item in contents]
        items_list = "\n".join(f"- {item.name}" for item in wrapped)
        return f"\n\nYou see:\n{items_list}"


class ViewUser:
    """View-friendly wrapper for IUser that formats output for display."""

    def __init__(self, user: IUser):
        self._user = user

    def __str__(self) -> str:
        """String representation: Discord mention."""
        return self.mention

    @property
    def mention(self) -> str:
        """Discord mention string for this user."""
        return self._user.mention

    @async_cached_property
    async def balance(self) -> int:
        """User's currency balance."""
        return await self._user.get_balance()


@dataclass
class ActionContext:
    """Context for executing an action command for passing to action templates."""

    e: ViewEntity
    user: ViewUser
    effects: EffectsCollector
    container: ViewEntity | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for template rendering.

        Note: We don't use asdict() because it tries to recursively copy nested
        objects, which fails for objects with unpicklable attributes.
        """
        return {
            "e": self.e,
            "user": self.user,
            "effects": self.effects,
            "container": self.container,
        }
