"""Zone and room loader for syncing world data to PostgreSQL and Discord."""

import csv
import io
import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast, get_args

import asyncpg

from mudd.utils.text import Rarity

logger = logging.getLogger(__name__)

# Valid rarity values - derived from the Rarity type to maintain single source of truth
VALID_RARITIES: set[str] = set(get_args(Rarity))


@dataclass
class ZoneData:
    """Zone data from rec file."""

    id: str
    name: str
    description: str | None = None


@dataclass
class RoomData:
    """Room data from rec file."""

    id: str
    name: str
    description: str
    zone_id: str
    has_voice: bool = False
    is_default: bool = False


@dataclass
class EntityData:
    """Entity data from rec file."""

    id: str
    name: str
    prototype_id: str | None = None
    container_id: str | None = None
    room: str | None = None
    contents_visible: bool | None = None
    rarity: Rarity = "none"
    tags: list[str] | None = None  # Space-separated in rec files
    description_short: str | None = None
    description_long: str | None = None
    on_look: str | None = None
    on_touch: str | None = None
    on_attack: str | None = None
    on_use: str | None = None
    on_take: str | None = None
    on_open: str | None = None
    on_close: str | None = None
    on_drop: str | None = None
    on_fish: str | None = None


@dataclass
class ShopData:
    """Shop data from rec file."""

    id: str
    name: str
    preferred_tag: str | None = None
    sell_spread: float = 0.5
    restock_tag: str | None = None
    restock_interval_minutes: int = 1440


@dataclass
class SpawningPoolData:
    """Spawning pool data from rec file."""

    id: str
    room: str
    tag_query: str
    container_id: str | None = None
    max_count: int = 1
    respawn_interval_minutes: int = 30
    no_duplicates: bool = False


def _load_records_from_rec[T](
    world_file: Path,
    record_type: str,
    row_parser: Callable[[dict[str, str]], T],
) -> list[T]:
    """
    Load records of a given type from a world rec file using rec2csv.

    Args:
        world_file: Path to the world .rec file
        record_type: The recutils record type (e.g., "Zone", "Room")
        row_parser: Function to convert a CSV row dict to a domain object

    Returns:
        List of parsed records
    """
    records: list[T] = []
    try:
        result = subprocess.run(
            ["rec2csv", "-t", record_type, str(world_file)],
            capture_output=True,
            text=True,
            check=True,
        )
        if result.stdout.strip():
            reader = csv.DictReader(io.StringIO(result.stdout))
            records.extend(row_parser(row) for row in reader)
    except subprocess.CalledProcessError as e:
        # Real errors: file not found, parse errors, etc.
        logger.error(f"Failed to parse {record_type} from {world_file}: {e.stderr}")
        raise

    logger.debug(f"Loaded {len(records)} {record_type.lower()}s from {world_file}")
    return records


def _parse_zone_row(row: dict[str, str]) -> ZoneData:
    """Parse a CSV row into a ZoneData object."""
    return ZoneData(
        id=row["Id"],
        name=row["Name"],
        description=row.get("Description") or None,
    )


def _parse_room_row(row: dict[str, str]) -> RoomData:
    """Parse a CSV row into a RoomData object."""
    has_voice_str = row.get("HasVoice", "").lower()
    has_voice = has_voice_str in ("yes", "true", "1")
    is_default_str = row.get("IsDefault", "").lower()
    is_default = is_default_str in ("yes", "true", "1")
    return RoomData(
        id=row["Id"],
        name=row["Name"],
        description=row["Description"],
        zone_id=row["Zone"],
        has_voice=has_voice,
        is_default=is_default,
    )


def load_zones_from_rec(world_file: Path) -> list[ZoneData]:
    """Load Zone records from a world rec file using rec2csv."""
    return _load_records_from_rec(world_file, "Zone", _parse_zone_row)


def load_rooms_from_rec(world_file: Path) -> list[RoomData]:
    """Load Room records from a world rec file using rec2csv."""
    return _load_records_from_rec(world_file, "Room", _parse_room_row)


def _parse_entity_row(row: dict[str, str]) -> EntityData:
    """Parse a CSV row into an EntityData object."""
    # Parse boolean with None support
    contents_visible_str = row.get("ContentsVisible", "").lower()
    contents_visible: bool | None = None
    if contents_visible_str in ("yes", "true", "1"):
        contents_visible = True
    elif contents_visible_str in ("no", "false", "0"):
        contents_visible = False

    # Parse rarity with default and validation
    rarity_raw = row.get("Rarity", "").lower() or "none"
    if rarity_raw not in VALID_RARITIES:
        raise ValueError(
            f"Entity '{row['Id']}' has invalid Rarity '{rarity_raw}'. "
            f"Valid values: {', '.join(sorted(VALID_RARITIES))}"
        )
    rarity = cast(Rarity, rarity_raw)

    # Parse tags (space-separated string)
    tags_str = row.get("Tags", "").strip()
    tags = tags_str.split() if tags_str else None

    return EntityData(
        id=row["Id"],
        name=row["Name"],
        prototype_id=row.get("Prototype") or None,
        container_id=row.get("Container") or None,
        room=row.get("Room") or None,
        contents_visible=contents_visible,
        rarity=rarity,
        tags=tags,
        description_short=row.get("DescriptionShort") or None,
        description_long=row.get("DescriptionLong") or None,
        on_look=row.get("OnLook") or None,
        on_touch=row.get("OnTouch") or None,
        on_attack=row.get("OnAttack") or None,
        on_use=row.get("OnUse") or None,
        on_take=row.get("OnTake") or None,
        on_open=row.get("OnOpen") or None,
        on_close=row.get("OnClose") or None,
        on_drop=row.get("OnDrop") or None,
        on_fish=row.get("OnFish") or None,
    )


def load_entities_from_rec(world_file: Path) -> list[EntityData]:
    """Load Entity records from a world rec file using rec2csv."""
    return _load_records_from_rec(world_file, "Entity", _parse_entity_row)


def _parse_spawning_pool_row(row: dict[str, str]) -> SpawningPoolData:
    """Parse a CSV row into a SpawningPoolData object."""
    # Parse max_count with default
    max_count_str = row.get("MaxCount", "1")
    try:
        max_count = int(max_count_str)
    except ValueError as e:
        raise ValueError(
            f"SpawningPool '{row['Id']}' has invalid MaxCount '{max_count_str}'. "
            f"Must be an integer."
        ) from e

    # Parse respawn_interval_minutes with default (30 minutes)
    interval_str = row.get("RespawnIntervalMinutes", "30")
    try:
        respawn_interval_minutes = int(interval_str)
    except ValueError as e:
        raise ValueError(
            f"SpawningPool '{row['Id']}' has invalid RespawnIntervalMinutes "
            f"'{interval_str}'. Must be an integer."
        ) from e

    # Parse no_duplicates boolean
    no_duplicates_str = row.get("NoDuplicates", "").lower()
    no_duplicates = no_duplicates_str in ("yes", "true", "1")

    return SpawningPoolData(
        id=row["Id"],
        room=row["Room"],
        tag_query=row["TagQuery"],
        container_id=row.get("Container") or None,
        max_count=max_count,
        respawn_interval_minutes=respawn_interval_minutes,
        no_duplicates=no_duplicates,
    )


def load_spawning_pools_from_rec(world_file: Path) -> list[SpawningPoolData]:
    """Load SpawningPool records from a world rec file using rec2csv.

    Returns empty list if no SpawningPool records exist (graceful handling).
    """
    try:
        return _load_records_from_rec(
            world_file, "SpawningPool", _parse_spawning_pool_row
        )
    except subprocess.CalledProcessError:
        # No SpawningPool records in file is OK
        return []


def _parse_shop_row(row: dict[str, str]) -> ShopData:
    """Parse a CSV row into a ShopData object."""
    # Parse sell_spread with default
    sell_spread_str = row.get("SellSpread", "0.5")
    try:
        sell_spread = float(sell_spread_str)
    except ValueError as e:
        raise ValueError(
            f"Shop '{row['Id']}' has invalid SellSpread '{sell_spread_str}'. "
            f"Must be a number."
        ) from e

    # Parse restock_interval_minutes with default (1440 = daily)
    interval_str = row.get("RestockIntervalMinutes", "1440")
    try:
        restock_interval_minutes = int(interval_str)
    except ValueError as e:
        raise ValueError(
            f"Shop '{row['Id']}' has invalid RestockIntervalMinutes "
            f"'{interval_str}'. Must be an integer."
        ) from e

    return ShopData(
        id=row["Id"],
        name=row["Name"],
        preferred_tag=row.get("PreferredTag") or None,
        sell_spread=sell_spread,
        restock_tag=row.get("RestockTag") or None,
        restock_interval_minutes=restock_interval_minutes,
    )


def load_shops_from_rec(world_file: Path) -> list[ShopData]:
    """Load Shop records from a world rec file using rec2csv.

    Returns empty list if no Shop records exist (graceful handling).
    """
    try:
        return _load_records_from_rec(world_file, "Shop", _parse_shop_row)
    except subprocess.CalledProcessError:
        # No Shop records in file is OK
        return []


def get_default_room(rooms: list[RoomData]) -> str:
    """Get the default room ID from loaded rooms.

    Raises ValueError if no default or multiple defaults found.
    """
    defaults = [r for r in rooms if r.is_default]
    if len(defaults) == 0:
        raise ValueError("No default room found. Mark one room with IsDefault: yes")
    if len(defaults) > 1:
        ids = [r.id for r in defaults]
        raise ValueError(f"Multiple default rooms found: {ids}. Only one allowed.")
    return defaults[0].id


async def sync_zones_and_rooms_to_db(
    pool: asyncpg.Pool,
    zones: list[ZoneData],
    rooms: list[RoomData],
    default_room: str,
) -> dict[str, int]:
    """
    Sync zones and rooms to database only (no Discord operations).

    This is the database-only portion of sync, useful for testing
    without requiring Discord mocking.

    Args:
        pool: Database connection pool
        zones: List of Zone objects to sync
        rooms: List of Room objects to sync
        default_room: Default room to relocate users to when their room is deleted

    Returns:
        Stats dict with counts: zones, rooms, users_relocated
    """
    stats = {"zones": 0, "rooms": 0, "users_relocated": 0}

    zone_ids = {z.id for z in zones}
    room_ids = {r.id for r in rooms}

    # Validate default_room exists in provided rooms
    if default_room not in room_ids:
        raise ValueError(
            f"Default room '{default_room}' not found in rooms. "
            f"Available rooms: {sorted(room_ids)}"
        )

    async with pool.acquire() as conn, conn.transaction():
        # Move users from deleted rooms to default room
        deleted_rooms_result = await conn.fetch(
            "SELECT id FROM rooms WHERE id != ALL($1::text[])",
            list(room_ids),
        )
        deleted_room_ids = [r["id"] for r in deleted_rooms_result]

        if deleted_room_ids:
            update_sql = (
                "UPDATE users SET current_room = $1 "
                "WHERE current_room = ANY($2::text[])"
            )
            result = await conn.execute(update_sql, default_room, deleted_room_ids)
            # Parse "UPDATE N" to get count
            if result.startswith("UPDATE "):
                stats["users_relocated"] = int(result.split()[1])
                if stats["users_relocated"] > 0:
                    logger.info(
                        f"Relocated {stats['users_relocated']} users from deleted rooms"
                    )

        # Delete rooms not in files (before zones due to FK)
        await conn.execute(
            "DELETE FROM rooms WHERE id != ALL($1::text[])",
            list(room_ids),
        )

        # Delete zones not in files
        await conn.execute(
            "DELETE FROM zones WHERE id != ALL($1::text[])",
            list(zone_ids),
        )

        # Upsert zones
        for zone in zones:
            await conn.execute(
                """INSERT INTO zones (id, name, description)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (id) DO UPDATE SET name = $2, description = $3""",
                zone.id,
                zone.name,
                zone.description,
            )
            stats["zones"] += 1

        # Upsert rooms
        for room in rooms:
            await conn.execute(
                """INSERT INTO rooms
                       (id, name, description, zone_id, has_voice, is_default)
                   VALUES ($1, $2, $3, $4, $5, $6)
                   ON CONFLICT (id) DO UPDATE SET
                       name = $2, description = $3, zone_id = $4, has_voice = $5,
                       is_default = $6""",
                room.id,
                room.name,
                room.description,
                room.zone_id,
                room.has_voice,
                room.is_default,
            )
            stats["rooms"] += 1

    logger.info(f"Synced {stats['zones']} zones and {stats['rooms']} rooms to database")
    return stats
