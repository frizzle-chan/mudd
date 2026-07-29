FROM docker.io/library/python:3.14.5-trixie AS production
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
LABEL org.opencontainers.image.source=https://github.com/frizzle-chan/mudd

ARG GIT_COMMIT=unknown

COPY --from=ghcr.io/astral-sh/uv:0.9.18 /uv /uvx /bin/

RUN groupadd --gid 1000 mudd \
 && useradd --uid 1000 --gid 1000 -m mudd --shell /bin/bash \
 && mkdir -p /app \
 && chown mudd:mudd /app

RUN cat <<'EOF' > /etc/apt/sources.list.d/backports.sources
Types: deb
URIs: http://deb.debian.org/debian
Suites: trixie-backports
Components: main
Enabled: yes
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
EOF
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends curl locales \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends -t trixie-backports recutils \
 && sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen \
 && locale-gen \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /usr/share/fonts/truetype/unifontex \
 && curl -sSL \
    -o /usr/share/fonts/truetype/unifontex/unifontex.ttf \
    https://github.com/stgiga/UnifontEX/releases/download/15.1jan23morePona/UnifontExMono.ttf

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

RUN echo "${GIT_COMMIT}" > /app/.commit_sha

RUN --mount=type=cache,target=/home/mudd/.cache/uv,uid=1000,gid=1000 \
    uv sync --locked

# Readiness endpoint served by mudd/health.py
EXPOSE 8080

# Generous start period: the first sync creates channels and can be slow on a
# large guild. Once started, three consecutive failures mark the bot unhealthy.
HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
    CMD curl -fsS "http://localhost:${HEALTH_PORT:-8080}/healthz" || exit 1

CMD [ "python", "main.py" ]

FROM production AS devcontainer

# The devcontainer runs `sleep infinity`, not the bot — inheriting the
# production healthcheck would permanently report it unhealthy.
HEALTHCHECK NONE

ENV UV_NO_DEV=0 \
    UV_COMPILE_BYTECODE=0 \
    UV_NO_CACHE=0 \
    UV_LINK_MODE=copy \
    DISABLE_TELEMETRY=1

USER root

# install stuff
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       curl \
       gifsicle \
       git \
       jpegoptim \
       jq \
       just \
       libpq5 \
       pngquant \
       postgresql-client \
       procps \
       ripgrep \
       tmux \
       vim \
       zsh \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* \
 && chsh -s /bin/zsh mudd

USER mudd
