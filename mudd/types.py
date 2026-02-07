"""Core type definitions for MUDD."""

from enum import StrEnum


class VerbAction(StrEnum):
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
    ON_FISH = "on_fish"
