default: lint format types entities squawk

test:
    uv run pytest

lint:
    uv run ruff check .

format:
    uv run ruff format .

types:
    uv run ty check

entities:
    recfix --check data/entities.rec

squawk:
    uv run squawk migrations/*.sql

devcontainer:
    gh auth login --with-token < .github-token.txt

# Reset dev database (drops and recreates schema, runs migrations)
resetdb:
    psql postgresql://mudd:mudd@db:5432/mudd -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
    uv run python -c "import asyncio; from mudd.services.database import init_database; asyncio.run(init_database())"
