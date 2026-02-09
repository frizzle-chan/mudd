#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Validate horse data: recfile integrity and required image assets."""

import subprocess
import sys
from pathlib import Path

HORSES_DIR = Path(__file__).parent.parent / "data" / "horses"
REQUIRED_SUFFIXES = ("_profile.png", "_race.png", "_victory.png")


def get_horse_ids() -> list[str]:
    """Extract horse IDs by catting all rec files through recsel."""
    rec_files = sorted(HORSES_DIR.glob("*.rec"))
    if not rec_files:
        print("No .rec files found in data/horses/", file=sys.stderr)
        sys.exit(1)

    cat = subprocess.run(
        ["cat", *(str(f) for f in rec_files)],
        capture_output=True,
        text=True,
        check=True,
    )
    result = subprocess.run(
        ["recsel", "-t", "Horse", "-P", "Id"],
        input=cat.stdout,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    horse_ids = get_horse_ids()
    errors: list[str] = []

    for horse_id in horse_ids:
        for suffix in REQUIRED_SUFFIXES:
            asset = HORSES_DIR / f"{horse_id}{suffix}"
            if not asset.exists():
                errors.append(f"Missing {asset.name} for horse '{horse_id}'")

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print(f"{len(horse_ids)} horses, all assets present - OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
