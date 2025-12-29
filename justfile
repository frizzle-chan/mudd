default: lint format

lint:
    uv run ruff check .

format:
    uv run ruff format .

devcontainer:
    gh auth login --with-token < .github-token.txt
