#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Validate a world rec file for internal uniqueness of Zone and Room IDs."""

import csv
import io
import subprocess
import sys
from collections import Counter
from pathlib import Path


def load_ids(rec_file: Path, record_type: str) -> list[str]:
    """Load IDs of a given record type from a rec file."""
    try:
        result = subprocess.run(
            ["rec2csv", "-t", record_type, str(rec_file)],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        if "error: no records" in e.stderr.lower():
            return []
        msg = f"Error parsing {record_type} from {rec_file}: {e.stderr}"
        print(msg, file=sys.stderr)
        raise

    ids: list[str] = []
    if result.stdout.strip():
        reader = csv.DictReader(io.StringIO(result.stdout))
        for row in reader:
            record_id = row.get("Id")
            if record_id:
                ids.append(record_id)
    return ids


def check_duplicates(rec_file: Path, record_type: str, ids: list[str]) -> list[str]:
    """Return error messages for any duplicate IDs."""
    counts = Counter(ids)
    return [
        f"{rec_file.name}: Duplicate {record_type} Id '{rid}' ({count}x)"
        for rid, count in counts.items()
        if count > 1
    ]


def main() -> int:
    """Validate Zone and Room IDs are unique within a world file.

    Usage: validate_world.py <file.rec>
    """
    if len(sys.argv) != 2:
        print("Usage: validate_world.py <file.rec>", file=sys.stderr)
        return 1

    rec_file = Path(sys.argv[1])
    if not rec_file.exists():
        print(f"File not found: {rec_file}", file=sys.stderr)
        return 1

    errors: list[str] = []
    zone_ids = load_ids(rec_file, "Zone")
    errors.extend(check_duplicates(rec_file, "Zone", zone_ids))

    room_ids = load_ids(rec_file, "Room")
    errors.extend(check_duplicates(rec_file, "Room", room_ids))

    if errors:
        print("Validation errors:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    print(f"{rec_file.name}: {len(zone_ids)} zones, {len(room_ids)} rooms - OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
