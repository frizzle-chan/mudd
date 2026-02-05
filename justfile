default: lint format types entities verbs squawk vulture

test:
    uv run pytest

testq:
    uv run pytest -qx --tb=line

lint:
    uv run ruff check .

format:
    uv run ruff format .

types:
    uv run ty check

ralph prompt_file="prompt.local.md":
    if [ ! -f {{prompt_file}} ]; then echo "{{prompt_file}} not found"; exit 1; fi
    claude --permission-mode acceptEdits '/ralph-loop:ralph-loop "execute @{{prompt_file}} and output <promise>FIN</promise> when done." --max-iterations 5 --completion-promise FIN'

entities:
    #!/usr/bin/env bash
    set -euo pipefail
    for file in data/worlds/*.rec; do
        recfix --check "$file"
    done
    uv run scripts/validate_world.py

verbs:
    uv run scripts/validate_verbs.py

squawk:
    uv run squawk migrations/*.sql

vulture:
    uv run vulture

# Generate room map from mansion.rec
map:
    uv run scripts/generate_room_map.py data/worlds/mansion.rec > data/worlds/mansion-map.mmd

devcontainer:
    gh auth login --with-token < .github-token.txt

# Reset dev database (drops and recreates schema, runs migrations)
resetdb:
    psql postgresql://mudd:mudd@db:5432/mudd -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

migratedb:
    uv run python -c "import asyncio; from mudd.database import init_database; asyncio.run(init_database())"

# Optimize images from img-src/ to img-dist/
images:
    uv run scripts/optimize_images.py
