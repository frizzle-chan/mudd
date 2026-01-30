"""Observer implementations for the MVC models.

This package provides observer classes that react to model events
and reconcile external state (e.g., Discord threads).
"""

from mudd.observers.discord import DiscordReconciler

__all__ = ["DiscordReconciler"]
