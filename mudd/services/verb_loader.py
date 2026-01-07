"""Verb loader for syncing verb word lists to PostgreSQL."""

import logging
from pathlib import Path

import asyncpg

from mudd.services.verb_action import VerbAction

logger = logging.getLogger(__name__)

VERBS_DIR = Path(__file__).parent.parent.parent / "data" / "verbs"

# Valid action names from VerbAction enum
VALID_ACTIONS = {action.value for action in VerbAction}


def load_verb_files() -> dict[VerbAction, list[str]]:
    """Load all verb files from data/verbs/ directory.

    Returns:
        Dict mapping VerbAction to list of verbs.

    Raises:
        FileNotFoundError: If verbs directory does not exist.
    """
    if not VERBS_DIR.exists():
        raise FileNotFoundError(f"Verbs directory not found: {VERBS_DIR}")

    verb_files: dict[VerbAction, list[str]] = {}

    for file in VERBS_DIR.glob("*.txt"):
        action_name = file.stem  # e.g., 'on_attack' from 'on_attack.txt'

        # Validate action name against enum
        if action_name not in VALID_ACTIONS:
            logger.warning(f"Skipping invalid action file: {file.name}")
            continue

        try:
            verbs = [
                line.strip().lower()
                for line in file.read_text().splitlines()
                if line.strip()
            ]
        except OSError as e:
            logger.error(f"Failed to read verb file {file.name}: {e}")
            raise

        action = VerbAction(action_name)
        verb_files[action] = verbs
        logger.debug(f"Loaded {len(verbs)} verbs for action '{action_name}'")

    return verb_files


async def sync_verbs(pool: asyncpg.Pool) -> int:
    """Sync verb files to database with full replacement.

    Deletes verbs not in current files, then upserts all current verbs.

    Returns:
        Number of verbs synced.

    Raises:
        FileNotFoundError: If verbs directory does not exist.
    """
    verb_files = load_verb_files()

    if not verb_files:
        logger.warning("No verb files found to sync")
        return 0

    # Collect all verbs
    all_verbs = {verb for verbs in verb_files.values() for verb in verbs}

    async with pool.acquire() as conn, conn.transaction():
        # Delete verbs not in current files
        deleted = await conn.execute(
            "DELETE FROM verbs WHERE verb != ALL($1::text[])",
            list(all_verbs),
        )
        if deleted != "DELETE 0":
            logger.info(f"Removed stale verbs: {deleted}")

        # Upsert all verbs
        for action, verbs in verb_files.items():
            for verb in verbs:
                await conn.execute(
                    """INSERT INTO verbs (verb, action) VALUES ($1, $2::verb_action)
                       ON CONFLICT (verb) DO UPDATE SET action = $2::verb_action""",
                    verb,
                    action.value,
                )

    total_verbs = sum(len(verbs) for verbs in verb_files.values())
    logger.info(f"Synced {total_verbs} verbs across {len(verb_files)} actions")
    return total_verbs
