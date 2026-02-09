"""Horse loader for syncing horse definitions from recfiles to PostgreSQL."""

from __future__ import annotations

import csv
import io
import logging
import subprocess
from dataclasses import dataclass
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
        # Attach image data
        horse = HorseData(
            id=horse.id,
            name=horse.name,
            speed=horse.speed,
            stamina=horse.stamina,
            consistency=horse.consistency,
            luck=horse.luck,
            active=horse.active,
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

        # Upsert current horses (preserve rolling-window counters)
        for horse in horses:
            await conn.execute(
                """INSERT INTO horses
                       (id, name, speed, stamina, consistency, luck, active,
                        profile_image, race_image, victory_image)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                   ON CONFLICT (id) DO UPDATE SET
                       name = $2, speed = $3, stamina = $4, consistency = $5,
                       luck = $6, active = $7,
                       profile_image = $8, race_image = $9, victory_image = $10""",
                horse.id,
                horse.name,
                horse.speed,
                horse.stamina,
                horse.consistency,
                horse.luck,
                horse.active,
                horse.profile_image,
                horse.race_image,
                horse.victory_image,
            )

    logger.info("Synced %d horses", len(horses))
    return len(horses)
