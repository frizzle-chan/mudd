default: lint format types

lint:
    uv run ruff check .

format:
    uv run ruff format .

types:
    uv run ty check

devcontainer:
    gh auth login --with-token < .github-token.txt
