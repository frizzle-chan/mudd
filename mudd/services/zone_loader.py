"""Zone and room loader for syncing world data to PostgreSQL and Discord."""

import csv
import io
import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import asyncpg
import discord

logger = logging.getLogger(__name__)

# Directory containing world .rec files (zones, rooms, entities)
WORLDS_DIR = Path(__file__).parent.parent.parent / "data" / "worlds"


@dataclass
class Zone:
    """Zone data from rec file."""

    id: str
    name: str
    description: str | None = None


@dataclass
class Room:
    """Room data from rec file."""

    id: str
    name: str
    description: str
    zone_id: str
    has_voice: bool = False


def _load_records_from_rec[T](
    record_type: str,
    row_parser: Callable[[dict[str, str]], T],
) -> list[T]:
    """
    Load records of a given type from rec files using rec2csv.

    Args:
        record_type: The recutils record type (e.g., "Zone", "Room")
        row_parser: Function to convert a CSV row dict to a domain object

    Returns:
        List of parsed records
    """
    rec_files = list(WORLDS_DIR.glob("*.rec"))
    if not rec_files:
        logger.warning(f"No .rec files found in {WORLDS_DIR}")
        return []

    records: list[T] = []
    for rec_file in rec_files:
        try:
            result = subprocess.run(
                ["rec2csv", "-t", record_type, str(rec_file)],
                capture_output=True,
                text=True,
                check=True,
            )
            if result.stdout.strip():
                reader = csv.DictReader(io.StringIO(result.stdout))
                records.extend(row_parser(row) for row in reader)
        except subprocess.CalledProcessError as e:
            # rec2csv returns error if no records of that type exist - this is OK
            if "error: no records" in e.stderr.lower():
                continue
            # Any other error is critical (corrupt file, missing rec2csv, etc.)
            logger.error(f"Failed to parse {record_type} from {rec_file}: {e.stderr}")
            raise

    logger.debug(f"Loaded {len(records)} {record_type.lower()}s from rec files")
    return records


def _parse_zone_row(row: dict[str, str]) -> Zone:
    """Parse a CSV row into a Zone object."""
    return Zone(
        id=row["Id"],
        name=row["Name"],
        description=row.get("Description") or None,
    )


def _parse_room_row(row: dict[str, str]) -> Room:
    """Parse a CSV row into a Room object."""
    has_voice_str = row.get("HasVoice", "").lower()
    has_voice = has_voice_str in ("yes", "true", "1")
    return Room(
        id=row["Id"],
        name=row["Name"],
        description=row["Description"],
        zone_id=row["Zone"],
        has_voice=has_voice,
    )


def load_zones_from_rec() -> list[Zone]:
    """Load Zone records from rec files using rec2csv."""
    return _load_records_from_rec("Zone", _parse_zone_row)


def load_rooms_from_rec() -> list[Room]:
    """Load Room records from rec files using rec2csv."""
    return _load_records_from_rec("Room", _parse_room_row)


async def sync_zones_and_rooms_to_db(
    pool: asyncpg.Pool,
    zones: list[Zone],
    rooms: list[Room],
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
                """INSERT INTO rooms (id, name, description, zone_id, has_voice)
                   VALUES ($1, $2, $3, $4, $5)
                   ON CONFLICT (id) DO UPDATE SET
                       name = $2, description = $3, zone_id = $4, has_voice = $5""",
                room.id,
                room.name,
                room.description,
                room.zone_id,
                room.has_voice,
            )
            stats["rooms"] += 1

    logger.info(f"Synced {stats['zones']} zones and {stats['rooms']} rooms to database")
    return stats


async def sync_zones_and_rooms(
    pool: asyncpg.Pool,
    guild: discord.Guild,
    default_room: str,
    console_channel_name: str = "console",
) -> dict[str, int]:
    """
    Sync zones and rooms from rec files to database and Discord.

    Creates missing Discord categories and channels, syncs channel topics,
    and reports orphan channels to the console channel.

    Returns:
        Stats dict with counts of operations performed.
    """
    stats: dict[str, int] = {
        "zones": 0,
        "rooms": 0,
        "users_relocated": 0,
        "categories_created": 0,
        "channels_created": 0,
        "voice_channels_created": 0,
        "topics_updated": 0,
        "orphans_found": 0,
    }

    # Load data from rec files
    zones = load_zones_from_rec()
    rooms = load_rooms_from_rec()

    if not zones:
        logger.warning("No zones found in rec files - skipping sync")
        return stats

    # Sync to database first
    db_stats = await sync_zones_and_rooms_to_db(pool, zones, rooms, default_room)
    stats.update(db_stats)

    zone_ids = {z.id for z in zones}
    room_ids = {r.id for r in rooms}

    # Discord sync: create categories and channels
    # Build zone -> category mapping
    zone_to_category: dict[str, discord.CategoryChannel] = {}
    for category in guild.categories:
        category_name = category.name.lower().replace(" ", "-")
        if category_name in zone_ids:
            zone_to_category[category_name] = category

    # Create missing categories
    for zone in zones:
        if zone.id not in zone_to_category:
            # Create category with @everyone denied view_channel (fog of war)
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False)
            }
            category = await guild.create_category(zone.name, overwrites=overwrites)
            zone_to_category[zone.id] = category
            stats["categories_created"] += 1
            logger.info(f"Created category: {zone.name}")

    # Create missing channels and sync topics
    for room in rooms:
        category = zone_to_category.get(room.zone_id)
        if not category:
            logger.warning(
                f"No category found for room {room.id} in zone {room.zone_id}"
            )
            continue

        # Find existing text channel
        text_channel = discord.utils.get(category.text_channels, name=room.id)

        if text_channel is None:
            # Create text channel
            text_channel = await category.create_text_channel(
                room.id,
                topic=room.description,
            )
            stats["channels_created"] += 1
            logger.info(f"Created channel: #{room.id} in {category.name}")
        elif text_channel.topic != room.description:
            # Sync topic
            await text_channel.edit(topic=room.description)
            stats["topics_updated"] += 1
            logger.debug(f"Updated topic for #{room.id}")

        # Handle voice channel
        if room.has_voice:
            voice_channel = discord.utils.get(category.voice_channels, name=room.id)

            if voice_channel is None:
                await category.create_voice_channel(room.id)
                stats["voice_channels_created"] += 1
                logger.info(f"Created voice channel: {room.id} in {category.name}")

    # Find orphan channels (in zone categories but not in rec files)
    orphans: list[tuple[str, str]] = []  # (channel_name, category_name)
    for zone in zones:
        category = zone_to_category.get(zone.id)
        if not category:
            continue

        for channel in category.channels:
            # Skip channels that match a known room (text or voice)
            if channel.name in room_ids:
                continue
            orphans.append((channel.name, category.name))

    stats["orphans_found"] = len(orphans)

    # Report orphans to console channel
    if orphans:
        console_channel = discord.utils.get(
            guild.text_channels, name=console_channel_name
        )
        if console_channel:
            orphan_list = "\n".join(f"- #{name} in {cat}" for name, cat in orphans)
            msg = (
                f"**Orphan channels detected** (not in .rec files):\n{orphan_list}\n\n"
                "Consider deleting these channels or adding them to the world file."
            )
            await console_channel.send(msg)
            logger.info(
                f"Reported {len(orphans)} orphan channels to #{console_channel_name}"
            )
        else:
            logger.warning(
                f"Console channel #{console_channel_name} not found - "
                f"cannot report {len(orphans)} orphan channels"
            )

    logger.info(
        f"Discord sync complete: {stats['categories_created']} categories, "
        f"{stats['channels_created']} channels, "
        f"{stats['voice_channels_created']} voice channels, "
        f"{stats['topics_updated']} topics updated, {stats['orphans_found']} orphans"
    )

    return stats
