#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Validate world rec files for global uniqueness of Zone and Room IDs."""

import csv
import io
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

WORLDS_DIR = Path(__file__).parent.parent / "data" / "worlds"


def load_ids_from_rec(record_type: str, id_field: str) -> dict[str, list[str]]:
    """Load IDs of a given record type from all rec files.

    Returns:
        Dict mapping ID -> list of file paths where that ID appears.
    """
    rec_files = list(WORLDS_DIR.glob("*.rec"))
    if not rec_files:
        print(f"Warning: No .rec files found in {WORLDS_DIR}", file=sys.stderr)
        return {}

    id_to_files: dict[str, list[str]] = defaultdict(list)

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
                for row in reader:
                    record_id = row.get(id_field)
                    if record_id:
                        id_to_files[record_id].append(rec_file.name)
        except subprocess.CalledProcessError as e:
            # rec2csv returns error if no records of that type exist - this is OK
            if "error: no records" in e.stderr.lower():
                continue
            print(
                f"Error parsing {record_type} from {rec_file}: {e.stderr}",
                file=sys.stderr,
            )
            raise

    return id_to_files


def check_uniqueness(record_type: str, id_to_files: dict[str, list[str]]) -> list[str]:
    """Check for duplicate IDs.

    Returns:
        List of error messages for duplicates found.
    """
    errors = []
    for record_id, files in id_to_files.items():
        if len(files) > 1:
            # Group by file to show count per file
            file_counts = defaultdict(int)
            for f in files:
                file_counts[f] += 1
            locations = ", ".join(f"{f} ({count}x)" for f, count in file_counts.items())
            errors.append(f"Duplicate {record_type} Id '{record_id}' in: {locations}")
    return errors


def main() -> int:
    """Validate Zone and Room IDs are globally unique.

    Returns:
        Exit code: 0 for success, 1 for validation errors.
    """
    all_errors: list[str] = []

    # Check Zone IDs
    zone_ids = load_ids_from_rec("Zone", "Id")
    zone_errors = check_uniqueness("Zone", zone_ids)
    all_errors.extend(zone_errors)

    # Check Room IDs
    room_ids = load_ids_from_rec("Room", "Id")
    room_errors = check_uniqueness("Room", room_ids)
    all_errors.extend(room_errors)

    if all_errors:
        print("Validation errors:", file=sys.stderr)
        for error in all_errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    zone_count = len(zone_ids)
    room_count = len(room_ids)
    print(f"Validated {zone_count} zones and {room_count} rooms - all IDs unique")
    return 0


if __name__ == "__main__":
    sys.exit(main())
