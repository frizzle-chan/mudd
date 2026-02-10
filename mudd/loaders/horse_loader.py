"""Horse loader for syncing horse definitions from recfiles to PostgreSQL."""

from __future__ import annotations

import csv
import io
import logging
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)

HORSES_DIR = Path(__file__).parent.parent.parent / "data" / "horses"

REQUIRED_SUFFIXES = ("_profile.png", "_race.png", "_victory.png")


@dataclass(frozen=True, slots=True)
class HorseData:
    """Horse definition parsed from a recfile."""

    id: str
    name: str
    speed: int
    stamina: int
    consistency: int
    luck: int
    active: bool
    profile_image: bytes | None
    race_image: bytes | None
    victory_image: bytes | None


def _parse_horse_row(row: dict[str, str]) -> HorseData:
    """Parse a CSV dict row into a HorseData object.

    Args:
        row: Dict from csv.DictReader with keys matching Horse record fields.

    Returns:
        Parsed HorseData instance.
    """
    active_str = row.get("Active", "").lower()
    # Default to True when absent; only False when explicitly set
    active = active_str not in ("false", "no", "0") if active_str else True

    return HorseData(
        id=row["Id"],
        name=row["Name"],
        speed=int(row["Speed"]),
        stamina=int(row["Stamina"]),
        consistency=int(row["Consistency"]),
        luck=int(row["Luck"]),
        active=active,
        profile_image=None,
        race_image=None,
        victory_image=None,
    )


def _load_image(horses_dir: Path, horse_id: str, suffix: str) -> bytes | None:
    """Load an image file for a horse, returning None if missing."""
    path = horses_dir / f"{horse_id}{suffix}"
    if path.exists():
        return path.read_bytes()
    return None


def load_horses_from_rec(horses_dir: Path = HORSES_DIR) -> list[HorseData]:
    """Load Horse records from recfiles using rec2csv.

    Concatenates all .rec files in the horses directory and pipes through
    rec2csv to extract Horse records as CSV.

    Args:
        horses_dir: Path to the horses data directory.

    Returns:
        List of parsed HorseData instances with image data attached.

    Raises:
        FileNotFoundError: If horses directory does not exist.
        subprocess.CalledProcessError: If rec2csv fails.
    """
    if not horses_dir.exists():
        raise FileNotFoundError(f"Horses directory not found: {horses_dir}")

    rec_files = sorted(horses_dir.glob("*.rec"))
    if not rec_files:
        logger.warning("No .rec files found in %s", horses_dir)
        return []

    # Cat all rec files and pipe to rec2csv
    cat = subprocess.run(
        ["cat", *(str(f) for f in rec_files)],
        capture_output=True,
        text=True,
        check=True,
    )
    result = subprocess.run(
        ["rec2csv", "-t", "Horse"],
        input=cat.stdout,
        capture_output=True,
        text=True,
        check=True,
    )

    if not result.stdout.strip():
        return []

    horses: list[HorseData] = []
    reader = csv.DictReader(io.StringIO(result.stdout))
    for row in reader:
        horse = _parse_horse_row(row)
        horse = replace(
            horse,
            profile_image=_load_image(horses_dir, horse.id, "_profile.png"),
            race_image=_load_image(horses_dir, horse.id, "_race.png"),
            victory_image=_load_image(horses_dir, horse.id, "_victory.png"),
        )
        horses.append(horse)

    logger.debug("Loaded %d horses from %s", len(horses), horses_dir)
    return horses


async def sync_horses(pool: asyncpg.Pool, horses_dir: Path = HORSES_DIR) -> int:
    """Sync horse definitions from recfiles to the database.

    Deletes horses not present in recfiles, upserts current ones.
    Preserves rolling-window counters (recent_races, recent_wins, recent_places)
    on conflict — only definition columns and images are updated.

    Args:
        pool: Database connection pool.
        horses_dir: Path to the horses data directory.

    Returns:
        Number of horses synced.
    """
    horses = load_horses_from_rec(horses_dir)

    if not horses:
        logger.warning("No horses found to sync")
        return 0

    horse_ids = [h.id for h in horses]

    async with pool.acquire() as conn, conn.transaction():
        # Delete stale horses not in recfiles
        deleted = await conn.execute(
            "DELETE FROM horses WHERE id != ALL($1::text[])",
            horse_ids,
        )
        if deleted != "DELETE 0":
            logger.info("Removed stale horses: %s", deleted)

        # Batch upsert current horses (preserve rolling-window counters)
        await conn.execute(
            """INSERT INTO horses
                   (id, name, speed, stamina, consistency, luck, active,
                    profile_image, race_image, victory_image)
               SELECT * FROM unnest(
                   $1::text[], $2::text[], $3::int[], $4::int[],
                   $5::int[], $6::int[], $7::bool[],
                   $8::bytea[], $9::bytea[], $10::bytea[]
               )
               ON CONFLICT (id) DO UPDATE SET
                   name = EXCLUDED.name,
                   speed = EXCLUDED.speed,
                   stamina = EXCLUDED.stamina,
                   consistency = EXCLUDED.consistency,
                   luck = EXCLUDED.luck,
                   active = EXCLUDED.active,
                   profile_image = EXCLUDED.profile_image,
                   race_image = EXCLUDED.race_image,
                   victory_image = EXCLUDED.victory_image""",
            [h.id for h in horses],
            [h.name for h in horses],
            [h.speed for h in horses],
            [h.stamina for h in horses],
            [h.consistency for h in horses],
            [h.luck for h in horses],
            [h.active for h in horses],
            [h.profile_image for h in horses],
            [h.race_image for h in horses],
            [h.victory_image for h in horses],
        )

    logger.info("Synced %d horses", len(horses))
    return len(horses)
