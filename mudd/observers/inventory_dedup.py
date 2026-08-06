"""Pure survivor selection for duplicate inventory forums.

Extracted from the reconciler so that every branch which can delete a Discord
channel is reachable from a function testable without mocks. The previous
implementation kept the *lowest* snowflake — in production that was an empty
shell while the newest forum held 100+ item threads and the user's wallet.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ForumCandidate:
    """A forum competing to be a user's canonical inventory.

    Attributes:
        id: Discord forum channel ID.
        thread_count: Threads the forum holds. Must be 0 only when emptiness
            has been *verified* — ``forum.threads`` caches active threads only.
        registered: Whether ``user_inventory_forums`` points this user at it.
    """

    id: int
    thread_count: int
    registered: bool


@dataclass(frozen=True, slots=True)
class DedupPlan:
    """What to do with each candidate.

    Attributes:
        survivor_id: The forum to keep and register.
        delete_ids: Losers that are verifiably empty and safe to delete.
        keep_ids: Losers that hold threads. Left in place for manual review —
            they cost a category slot, which is the price of making an
            accidental content wipe structurally impossible.
    """

    survivor_id: int
    delete_ids: tuple[int, ...]
    keep_ids: tuple[int, ...]


def plan_dedup(candidates: Sequence[ForumCandidate]) -> DedupPlan:
    """Choose a survivor and classify the losers.

    Survivor precedence: registered to this user, then most threads, then
    newest ID. The result does not depend on input order.

    In practice ``registered`` is always False on the recovery path — the
    user's row is absent or was just deleted, which is what got us here. It is
    kept as defence-in-depth for any future caller; the protections doing the
    real work are the cross-user filter applied before this call and the
    thread count.

    Raises:
        ValueError: if ``candidates`` is empty.
    """
    if not candidates:
        raise ValueError("plan_dedup requires at least one candidate")

    survivor = max(candidates, key=lambda c: (c.registered, c.thread_count, c.id))
    losers = [c for c in candidates if c.id != survivor.id]

    return DedupPlan(
        survivor_id=survivor.id,
        delete_ids=tuple(c.id for c in losers if c.thread_count == 0),
        keep_ids=tuple(c.id for c in losers if c.thread_count > 0),
    )
