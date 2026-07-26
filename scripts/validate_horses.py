#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Validate horse data: recfile integrity, assets, and stat guidelines."""

import subprocess
import sys
from pathlib import Path

HORSES_DIR = Path(__file__).parent.parent / "data" / "horses"
REQUIRED_SUFFIXES = ("_profile.png", "_race.png", "_victory.png")
STAT_FIELDS = ("Speed", "Stamina", "Consistency", "Luck")
MIN_SPIKE = 75
MAX_DUMP = 35
MIN_BUDGET = 195
MAX_BUDGET = 250


def cat_rec_files() -> str:
    """Concatenate all rec files and return combined content."""
    rec_files = sorted(HORSES_DIR.glob("*.rec"))
    if not rec_files:
        print("No .rec files found in data/horses/", file=sys.stderr)
        sys.exit(1)

    result = subprocess.run(
        ["cat", *(str(f) for f in rec_files)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def get_horse_ids(content: str) -> list[str]:
    """Extract horse IDs from combined rec content."""
    result = subprocess.run(
        ["recsel", "-t", "Horse", "-P", "Id"],
        input=content,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def get_horse_stats(content: str) -> dict[str, dict[str, int]]:
    """Extract {horse_id: {stat: value}} from combined rec content."""
    result = subprocess.run(
        ["recsel", "-t", "Horse"],
        input=content,
        capture_output=True,
        text=True,
        check=True,
    )
    horses: dict[str, dict[str, int]] = {}
    current_id = ""
    current_stats: dict[str, int] = {}
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            if current_id:
                horses[current_id] = current_stats
                current_id = ""
                current_stats = {}
            continue
        key, _, value = stripped.partition(": ")
        if key == "Id":
            current_id = value
        elif key in STAT_FIELDS:
            current_stats[key] = int(value)
    if current_id:
        horses[current_id] = current_stats
    return horses


def check_trailing_blank_lines() -> list[str]:
    """Check that every horse .rec file ends with a trailing blank line."""
    errors: list[str] = []
    for path in sorted(HORSES_DIR.glob("*.rec")):
        if path.name == "00_horse.rec":
            continue
        text = path.read_text()
        if text and not text.endswith("\n\n"):
            errors.append(
                f"{path.name}: missing trailing blank line "
                f"(records will merge during concatenation)"
            )
    return errors


def main() -> int:
    errors = check_trailing_blank_lines()
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    content = cat_rec_files()
    horse_ids = get_horse_ids(content)
    stats = get_horse_stats(content)

    for horse_id in horse_ids:
        for suffix in REQUIRED_SUFFIXES:
            asset = HORSES_DIR / f"{horse_id}{suffix}"
            if not asset.exists():
                errors.append(f"Missing {asset.name} for horse '{horse_id}'")

        if horse_id in stats:
            values = list(stats[horse_id].values())
            total = sum(values)
            highest = max(values)
            lowest = min(values)
            if highest < MIN_SPIKE:
                errors.append(
                    f"Horse '{horse_id}': no spike stat >= {MIN_SPIKE} "
                    f"(highest is {highest})"
                )
            if lowest > MAX_DUMP:
                errors.append(
                    f"Horse '{horse_id}': no dump stat <= {MAX_DUMP} "
                    f"(lowest is {lowest})"
                )
            if total < MIN_BUDGET or total > MAX_BUDGET:
                errors.append(
                    f"Horse '{horse_id}': stat budget {total} "
                    f"outside range {MIN_BUDGET}\u2013{MAX_BUDGET}"
                )

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print(f"{len(horse_ids)} horses, all valid - OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
