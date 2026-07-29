#!/bin/bash
# SessionStart hook for Claude Code on the web.
#
# The web container ships uv, a postgres client and a stopped postgres 16
# cluster, but none of the project's own dependencies. This installs
# everything `just` and `pytest` need:
#
#   - recutils      -> `just entities` / `just horses` run recfix
#   - UnifontEX     -> mudd/rendering/chrome.py, image regression baselines
#   - postgres      -> tests/conftest.py creates ephemeral databases
#   - uv sync       -> pytest, ruff, ty, vulture, squawk
#
# Safe to re-run: every step is a no-op once it has succeeded.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  SUDO="sudo"
fi

# Run a command as the postgres superuser. `$SUDO -u postgres` cannot be used
# here: as root $SUDO is empty and the -u would be read as the command.
as_postgres() {
  if command -v sudo >/dev/null 2>&1; then
    sudo -u postgres "$@"
  else
    su postgres -c "$(printf '%q ' "$@")"
  fi
}

FONT_DIR=/usr/share/fonts/truetype/unifontex
FONT_URL=https://github.com/stgiga/UnifontEX/releases/download/15.1jan23morePona/UnifontExMono.ttf

# --- recutils ------------------------------------------------------------
if ! command -v recfix >/dev/null 2>&1; then
  echo "==> Installing recutils"
  # Third-party PPAs in this image are unreachable; their failures must not
  # abort the run as long as the Ubuntu archive lists refreshed.
  $SUDO apt-get update -qq || true
  DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y -qq recutils
fi

# --- UnifontEX -----------------------------------------------------------
# Required, not optional: chrome.py silently falls back to PIL's default font,
# which makes every *_image_test.py mismatch its checked-in baseline.
if [ ! -s "$FONT_DIR/unifontex.ttf" ]; then
  echo "==> Installing UnifontEX"
  $SUDO mkdir -p "$FONT_DIR"
  $SUDO curl -fsSL --retry 3 -o "$FONT_DIR/unifontex.ttf" "$FONT_URL"
  $SUDO fc-cache -f >/dev/null 2>&1 || true
fi

# --- PostgreSQL ----------------------------------------------------------
# The devcontainer reaches postgres at host `db`; here it is local, so tests
# need DB_HOST=localhost (see tests/conftest.py).
if ! pg_isready -h localhost -q 2>/dev/null; then
  echo "==> Starting PostgreSQL"
  read -r PG_VERSION PG_CLUSTER _ < <(pg_lsclusters -h | head -1)
  $SUDO pg_ctlcluster "$PG_VERSION" "$PG_CLUSTER" start

  for _ in $(seq 30); do
    pg_isready -h localhost -q 2>/dev/null && break
    sleep 1
  done
  pg_isready -h localhost
fi

psql_super() { as_postgres psql -tAc "$1"; }

if [ "$(psql_super "SELECT 1 FROM pg_roles WHERE rolname='mudd'")" != "1" ]; then
  echo "==> Creating role mudd"
  psql_super "CREATE ROLE mudd LOGIN SUPERUSER PASSWORD 'mudd'" >/dev/null
fi

if [ "$(psql_super "SELECT 1 FROM pg_database WHERE datname='mudd'")" != "1" ]; then
  echo "==> Creating database mudd"
  psql_super "CREATE DATABASE mudd OWNER mudd" >/dev/null
fi

# --- Python dependencies -------------------------------------------------
echo "==> Syncing dependencies"
uv sync --locked

# --- Session environment -------------------------------------------------
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    echo 'export DB_HOST=localhost'
    echo 'export DATABASE_URL=postgresql://mudd:mudd@localhost:5432/mudd'
  } >> "$CLAUDE_ENV_FILE"
fi

echo "==> Ready: uv run pytest (DB_HOST=localhost)"
