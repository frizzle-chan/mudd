FROM python:3.14-trixie AS production
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
LABEL org.opencontainers.image.source=https://github.com/frizzle-chan/mudd

COPY --from=ghcr.io/astral-sh/uv:0.9.18 /uv /uvx /bin/

RUN groupadd --gid 1000 mudd \
 && useradd --uid 1000 --gid 1000 -m mudd --shell /bin/bash \
 && mkdir -p /app \
 && chown mudd:mudd /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends locales \
 && sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen \
 && locale-gen \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

USER mudd

WORKDIR /app

ENV LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8 \
    UV_NO_DEV=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_CACHE_DIR=/home/mudd/.cache/uv/ \
    PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PATH=/app/.venv/bin:/home/mudd/.local/bin:$PATH

# Install dependencies
RUN --mount=type=cache,target=/home/mudd/.cache/uv,uid=1000,gid=1000 \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

COPY . .

RUN --mount=type=cache,target=/home/mudd/.cache/uv,uid=1000,gid=1000 \
    uv sync --locked

CMD [ "python", "main.py" ]

FROM production AS devcontainer

ENV UV_NO_DEV=0 \
    UV_COMPILE_BYTECODE=0 \
    UV_NO_CACHE=0 \
    UV_LINK_MODE=copy \
    DISABLE_TELEMETRY=1

USER root

# install stuff
RUN cat <<'EOF' > /etc/apt/sources.list.d/backports.sources
Types: deb deb-src
URIs: http://deb.debian.org/debian
Suites: trixie-backports
Components: main
Enabled: yes
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
EOF
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
       curl \
       git \
       jq \
       just \
       procps \
       redis-server \
       ripgrep \
       vim \
       zsh \
 && apt-get install -y --no-install-recommends -t trixie-backports \
       recutils \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* \
 && chsh -s /bin/zsh mudd

USER mudd
