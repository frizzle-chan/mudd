"""MVC Models for MUDD.

This package provides standalone model classes that encapsulate database
access and business logic for core domain objects.

Models are frozen dataclasses with classmethods for queries and instance
methods for mutations. Mutations return new instances (immutable pattern).
"""

from mudd.models.entity import EntityInstance, InstanceThreadInfo, ResolvedEntity
from mudd.models.entity_definition import EntityDefinition
from mudd.models.interfaces import IEntityInstance, IReadableEntity, IRoom, IUser
from mudd.models.inventory_forum import UserInventoryForum
from mudd.models.room import EntityModal, InventoryThread, Room, RoomEntityInstance
from mudd.models.skills import UserSkill, XPResult
from mudd.models.spawning_pool import SpawningPool
from mudd.models.user import FocusContext, TransferError, TransferResult, User
from mudd.models.zone import SyncStats, Zone

__all__ = [
    # Entity models
    "ResolvedEntity",
    "EntityInstance",
    "InstanceThreadInfo",
    "EntityDefinition",
    # Inventory forum model
    "UserInventoryForum",
    # SpawningPool model
    "SpawningPool",
    # User model
    "User",
    "FocusContext",
    "TransferError",
    "TransferResult",
    # Room model
    "Room",
    "RoomEntityInstance",
    "EntityModal",
    "InventoryThread",
    # Skills model
    "UserSkill",
    "XPResult",
    # Zone model
    "Zone",
    "SyncStats",
    # Protocols
    "IUser",
    "IRoom",
    "IReadableEntity",
    "IEntityInstance",
]
