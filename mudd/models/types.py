"""Type aliases for the models package."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mudd.models.entity import EntityInstance

# Observer callback type for entity lifecycle events.
# Called with (instance, event_name) when an entity changes state.
# Event names: "picked_up", "dropped", "destroyed"
Observer = Callable[["EntityInstance", str], None]
