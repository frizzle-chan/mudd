default: lint format types entities verbs squawk

test:
    uv run pytest

lint:
    uv run ruff check .

format:
    uv run ruff format .

types:
    uv run ty check

entities:
    #!/usr/bin/env bash
    set -euo pipefail
    for file in data/worlds/*.rec; do
        recfix --check "$file"
    done

verbs:
    #!/usr/bin/env bash
    set -euo pipefail
    # Check for duplicates (filter empty lines, normalize case)
    all_verbs=$(cat data/verbs/*.txt | grep -v '^$' | tr '[:upper:]' '[:lower:]' | sort)
    unique_verbs=$(echo "$all_verbs" | uniq)
    if [ "$all_verbs" != "$unique_verbs" ]; then
        echo "Duplicate verbs found:"
        echo "$all_verbs" | uniq -d
        exit 1
    fi
    # Check each file is sorted
    for file in data/verbs/*.txt; do
        if ! diff -q <(grep -v '^$' "$file") <(grep -v '^$' "$file" | sort) > /dev/null 2>&1; then
            echo "File not sorted: $file"
            exit 1
        fi
    done

squawk:
    uv run squawk migrations/*.sql

# Generate room map in mansion.md and mansion.mmd from mansion.rec
map:
    #!/usr/bin/env bash
    set -euo pipefail
    mermaid=$(uv run scripts/generate_room_map.py data/worlds/mansion.rec)
    # Replace content between markers in .md
    awk -v content="$mermaid" '
        /<!-- begin map -->/ { print; print content; skip=1; next }
        /<!-- end map -->/ { skip=0 }
        !skip { print }
    ' data/worlds/mansion.md > data/worlds/mansion.md.tmp
    mv data/worlds/mansion.md.tmp data/worlds/mansion.md
    # Write raw mermaid (without code fences) to .mmd
    echo "$mermaid" | sed '1d;$d' > data/worlds/mansion.mmd

devcontainer:
    gh auth login --with-token < .github-token.txt

# Reset dev database (drops and recreates schema, runs migrations)
resetdb:
    psql postgresql://mudd:mudd@db:5432/mudd -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
    uv run python -c "import asyncio; from mudd.services.database import init_database; asyncio.run(init_database())"
