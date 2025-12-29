default: lint format

lint:
    ruff check .

format:
    ruff format .

devcontainer:
    gh auth login --with-token < .github-token.txt
