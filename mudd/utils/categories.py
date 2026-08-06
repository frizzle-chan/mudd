"""Overflow-aware Discord category resolution.

Discord caps a category at 50 channels. Rather than fail once the cap is hit,
these helpers resolve a family of categories named ``Base``, ``Base 2``,
``Base 3`` … choosing the lowest-index one with room and creating the next
overflow category when every one is full.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

import discord

logger = logging.getLogger(__name__)

CATEGORY_CHANNEL_CAP = 50

# Floor for the per-call attempt budget. The real budget scales with the size
# of the category family — see `_attempt_budget`.
MIN_OVERFLOW_ATTEMPTS = 3

# Discord's message when a category is at its channel limit. The error code
# (50035, "Invalid Form Body") is far too generic to key off on its own.
_CATEGORY_FULL_MESSAGE = "Maximum number of channels in category"

type CategoryOverwrites = dict[
    discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite
]


@dataclass(frozen=True, slots=True)
class CategorySlot:
    """A category reduced to what resolution needs: identity and occupancy."""

    id: int
    name: str
    channel_count: int


def category_index(name: str, base: str) -> int:
    """Return a category's overflow index, or 0 when it is not in the family.

    The bare base name is index 1; ``"{base} N"`` is index N for N >= 2.
    ``"{base} 1"`` deliberately does not match — we never create that name, and
    accepting it would make :func:`next_category_name` ambiguous.
    """
    if name == base:
        return 1
    match = re.fullmatch(rf"{re.escape(base)} (\d+)", name)
    if match is None:
        return 0
    index = int(match.group(1))
    return index if index >= 2 else 0


def matches_category(name: str, base: str) -> bool:
    """Whether a category name belongs to the ``base`` overflow family."""
    return category_index(name, base) > 0


def select_category(slots: Sequence[CategorySlot], base: str) -> CategorySlot | None:
    """Lowest-index category in the family with room, or None when all are full.

    Ordering is by overflow index, not Discord position, so resolution is
    deterministic no matter how the guild is arranged.
    """
    indexed = [(category_index(s.name, base), s) for s in slots]
    for _, slot in sorted(
        (pair for pair in indexed if pair[0] > 0), key=lambda pair: pair[0]
    ):
        if slot.channel_count < CATEGORY_CHANNEL_CAP:
            return slot
    return None


def next_category_name(slots: Sequence[CategorySlot], base: str) -> str:
    """Name for the next overflow category: the base name, else max index + 1."""
    indices = [i for i in (category_index(s.name, base) for s in slots) if i > 0]
    if not indices:
        return base
    return f"{base} {max(indices) + 1}"


def attempt_budget(family_size: int) -> int:
    """How many creation attempts `create_with_overflow` gets for one call.

    Every existing category in the family can burn one attempt by looking like
    it has room (stale channel cache) and then rejecting the create as full.
    The budget therefore has to exceed the family size, or all attempts are
    spent proving categories full and the call errors out *before* reaching the
    branch that creates the next overflow category — reintroducing the exact
    hard failure this module exists to prevent.

    One attempt per existing category, plus one to create and use the new one,
    plus one of margin.
    """
    return max(MIN_OVERFLOW_ATTEMPTS, family_size + 2)


def _to_slot(category: discord.CategoryChannel) -> CategorySlot:
    return CategorySlot(
        id=category.id, name=category.name, channel_count=len(category.channels)
    )


def matching_categories(
    guild: discord.Guild, base: str
) -> list[discord.CategoryChannel]:
    """Every category in the ``base`` family, ordered by overflow index.

    Synchronous: ``guild.categories`` is a local cache read, no API call.

    Scans (forum recovery, orphan pruning) must use this rather than the single
    resolved category — otherwise a user whose forum lives in ``Inventory``
    could resolve to ``Inventory 2`` and get a second forum created.
    """
    indexed = [(category_index(c.name, base), c) for c in guild.categories]
    return [
        c
        for _, c in sorted(
            (pair for pair in indexed if pair[0] > 0), key=lambda pair: pair[0]
        )
    ]


async def create_with_overflow[T: discord.abc.GuildChannel](
    guild: discord.Guild,
    base: str,
    overwrites: CategoryOverwrites,
    create_fn: Callable[[discord.CategoryChannel], Awaitable[T]],
    *,
    reason: str | None = None,
) -> T:
    """Create a channel under the ``base`` family, overflowing as needed.

    Resolves a category with room (creating the next overflow category when all
    are full) and calls ``create_fn`` with it.

    Tolerates a stale local cache: discord.py does not add a newly created
    channel to ``guild.channels`` until the ``GUILD_CHANNEL_CREATE`` gateway
    event arrives, so within one sync pass ``len(category.channels)`` can
    undercount channels this same pass just created. When ``create_fn`` reports
    a full category, that category is marked full for the rest of this call and
    resolution is retried. The attempt budget scales with the family size (see
    :func:`attempt_budget`) so that every existing category can be proven full
    and the next overflow category still gets created.

    ``created`` is local to one call, so two concurrent calls inside the same
    gateway-lag window can each create a category named ``"Base 2"``.
    Resolution still behaves correctly — duplicate names share an overflow
    index and both are scanned — and the cost is a stray empty category.

    Raises:
        discord.HTTPException: any Discord error other than a full category.
        RuntimeError: overflow attempts exhausted.
    """
    full: set[int] = set()
    created: list[discord.CategoryChannel] = []
    attempts = attempt_budget(len(matching_categories(guild, base)))

    for _ in range(attempts):
        cached_ids = {c.id for c in guild.categories}
        known = list(guild.categories) + [c for c in created if c.id not in cached_ids]
        chosen = select_category([_to_slot(c) for c in known if c.id not in full], base)

        if chosen is None:
            name = next_category_name([_to_slot(c) for c in known], base)
            category = await guild.create_category(
                name, overwrites=overwrites, reason=reason
            )
            created.append(category)
            logger.info("Created overflow category '%s' in %s", name, guild.name)
        else:
            category = next(c for c in known if c.id == chosen.id)

        try:
            return await create_fn(category)
        except discord.HTTPException as e:
            if _CATEGORY_FULL_MESSAGE not in str(e):
                raise
            logger.warning(
                "Category '%s' (%d) is at capacity, retrying with overflow",
                category.name,
                category.id,
            )
            full.add(category.id)

    raise RuntimeError(
        f"Exhausted {attempts} overflow attempts creating a channel "
        f"under '{base}' in {guild.name}"
    )
