#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Add a verb to a word list, ensuring no duplicates across all files."""

import argparse
import fcntl
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

VERBS_DIR = Path(__file__).parent.parent / "data" / "verbs"
VALID_ACTIONS = ["on_look", "on_touch", "on_attack", "on_use", "on_take"]
LOCK_FILE = VERBS_DIR / ".lock"


@contextmanager
def verb_lock() -> Iterator[None]:
    """Acquire exclusive lock for verb file operations."""
    VERBS_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add a verb to a word list, ensuring no duplicates."
    )
    parser.add_argument(
        "--action",
        required=True,
        choices=VALID_ACTIONS,
        help="The action category to add the verb to",
    )
    parser.add_argument("--verb", required=True, help="The verb to add")
    args = parser.parse_args()

    verb = args.verb.lower().strip()
    if not verb:
        print("Error: verb cannot be empty", file=sys.stderr)
        sys.exit(1)

    with verb_lock():
        # Check all files for duplicates
        for action in VALID_ACTIONS:
            path = VERBS_DIR / f"{action}.txt"
            if path.exists():
                verbs = [v.strip() for v in path.read_text().splitlines() if v.strip()]
                if verb in [v.lower() for v in verbs]:
                    print(f"Error: '{verb}' already exists in {path}", file=sys.stderr)
                    sys.exit(1)

        # Add verb and sort
        target = VERBS_DIR / f"{args.action}.txt"
        if target.exists():
            verbs = [v.strip() for v in target.read_text().splitlines() if v.strip()]
        else:
            verbs = []
        verbs.append(verb)
        verbs = sorted(set(verbs))
        target.write_text("\n".join(verbs) + "\n")
        print(f"Added '{verb}' to {target}")


if __name__ == "__main__":
    main()
