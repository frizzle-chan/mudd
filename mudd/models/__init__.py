"""MVC Models for MUDD.

This package provides standalone model classes that encapsulate database
access and business logic for core domain objects.

Models are frozen dataclasses with classmethods for queries and instance
methods for mutations. Mutations return new instances (immutable pattern).
"""

from mudd.models.entity import EntityInstance, ResolvedEntity
from mudd.models.entity_definition import EntityDefinition
from mudd.models.interfaces import IEntityInstance, IRoom, IUser
from mudd.models.room import EntityModal, InventoryThread, Room
from mudd.models.spawning_pool import SpawningPool
from mudd.models.user import FocusContext, TransferError, TransferResult, User
from mudd.models.zone import SyncStats, Zone

__all__ = [
    # Entity models
    "ResolvedEntity",
    "EntityInstance",
    "EntityDefinition",
    # SpawningPool model
    "SpawningPool",
    # User model
    "User",
    "FocusContext",
    "TransferError",
    "TransferResult",
    # Room model
    "Room",
    "EntityModal",
    "InventoryThread",
    # Zone model
    "Zone",
    "SyncStats",
    # Protocols
    "IUser",
    "IRoom",
    "IEntityInstance",
]
