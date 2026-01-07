"""Verb action enum mirroring PostgreSQL verb_action type."""

from enum import Enum


class VerbAction(str, Enum):
    """Action types for verb-to-handler mapping.

    Values match the PostgreSQL verb_action enum and entity handler column names.
    """

    ON_LOOK = "on_look"
    ON_TOUCH = "on_touch"
    ON_ATTACK = "on_attack"
    ON_USE = "on_use"
    ON_TAKE = "on_take"
