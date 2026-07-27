#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Validate verb word lists: check for duplicates and sorting."""

import sys
from pathlib import Path

VERBS_DIR = Path(__file__).parent.parent / "data" / "verbs"


def main() -> int:
    errors = 0

    # Collect all verbs to check for duplicates
    all_verbs: dict[str, str] = {}  # verb -> file it was found in

    for path in sorted(VERBS_DIR.glob("on_*.txt")):
        verbs = [v.strip() for v in path.read_text().splitlines() if v.strip()]

        # Check for duplicates across files
        for verb in verbs:
            lower_verb = verb.lower()
            if lower_verb in all_verbs:
                other = all_verbs[lower_verb]
                print(f"Duplicate verb '{verb}' in {path.name} (also in {other})")
                errors += 1
            else:
                all_verbs[lower_verb] = path.name

        # Check sorting (Python's default sort)
        sorted_verbs = sorted(set(verbs))
        if verbs != sorted_verbs:
            print(f"File not sorted: {path}")
            errors += 1

    return errors


if __name__ == "__main__":
    sys.exit(main())
