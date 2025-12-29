default: lint format typecheck

lint:
    uv run ruff check .

format:
    uv run ruff format .

typecheck:
    uv run ty check

devcontainer:
    gh auth login --with-token < .github-token.txt
