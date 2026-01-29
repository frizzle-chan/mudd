"""MVC Models for MUDD.

This package provides standalone model classes that encapsulate database
access and business logic for core domain objects.

Models are frozen dataclasses with classmethods for queries and instance
methods for mutations. Mutations return new instances (immutable pattern).
"""

from mudd.models.entity import EntityInstance, FocusMode, ResolvedEntity
from mudd.models.interfaces import IEntityInstance, IRoom, IUser
from mudd.models.room import Room
from mudd.models.types import Observer
from mudd.models.user import FocusContext, User

__all__ = [
    # Entity models
    "ResolvedEntity",
    "EntityInstance",
    "FocusMode",
    # User model
    "User",
    "FocusContext",
    # Room model
    "Room",
    # Types
    "Observer",
    # Protocols
    "IUser",
    "IRoom",
    "IEntityInstance",
]
