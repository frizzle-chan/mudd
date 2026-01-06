default: lint format types entities

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

devcontainer:
    gh auth login --with-token < .github-token.txt
