"""Core type definitions for MUDD."""

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class UserContext:
    """User information available in templates.

    Provides user-specific context for template rendering, allowing
    templates to reference the interacting user's name and mention.
    """

    name: str  # display_name
    mention: str  # @mention string


class VerbAction(str, Enum):
    """Action types for verb-to-handler mapping.

    Values match the PostgreSQL verb_action enum and entity handler column names.
    """

    ON_LOOK = "on_look"
    ON_TOUCH = "on_touch"
    ON_ATTACK = "on_attack"
    ON_USE = "on_use"
    ON_TAKE = "on_take"
    ON_OPEN = "on_open"
    ON_CLOSE = "on_close"
    ON_DROP = "on_drop"
