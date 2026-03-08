"""Validate YAML dialog trees: check structure, references, and consistency."""

import sys
from pathlib import Path

from mudd.loaders.dialog_loader import load_dialog

DIALOGS_DIR = Path(__file__).parent.parent / "data" / "dialogs"


def main() -> int:
    if not DIALOGS_DIR.is_dir():
        return 0

    yaml_files = sorted(DIALOGS_DIR.glob("*.yaml"))
    if not yaml_files:
        return 0

    errors = 0
    ids: dict[str, str] = {}  # dialog_id -> filename

    for path in yaml_files:
        try:
            tree = load_dialog(path)
        except Exception as e:
            print(f"{path.name}: {e}")
            errors += 1
            continue

        # Check for duplicate dialog IDs across files
        if tree.id in ids:
            print(
                f"{path.name}: duplicate dialog id '{tree.id}' (also in {ids[tree.id]})"
            )
            errors += 1
        else:
            ids[tree.id] = path.name

    if not errors:
        print(f"Validated {len(yaml_files)} dialog(s)")

    return errors


if __name__ == "__main__":
    sys.exit(main())
