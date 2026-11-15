# syntax=docker/dockerfile:1

# Pinned external tools. Only the secret loader is copied into the runtime image.
FROM ghcr.io/astral-sh/uv:0.9.8 AS uv
FROM infisical/cli:0.45.8 AS infisical

# Shared Python/OS base keeps the dependency and runtime stages ABI-compatible.
FROM python:3.14.10-slim-trixie AS python-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Apply available Debian security updates and remove downloaded package indexes.
RUN apt-get update \
    && apt-get upgrade --yes --no-install-recommends \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install locked application dependencies separately from frequently changing code.
FROM python-base AS dependencies

COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Application image: preinstalled dependencies, secret loader, and application code.
FROM python-base AS runtime

COPY --from=dependencies /app/.venv /app/.venv
COPY --from=infisical /bin/infisical /usr/local/bin/infisical
COPY . .

# Dependencies are already installed; remove unused pip and its bootstrap wheels.
RUN /usr/local/bin/python -m pip uninstall --yes pip \
    && rm -rf /usr/local/lib/python3.14/ensurepip

# Keep application code read-only and grant writes only to runtime data directories.
RUN useradd --uid 10001 --create-home gymu \
    && mkdir -p /app/data/member-photos /app/staticfiles \
    && chown -R gymu:gymu /app/data /app/staticfiles \
    && chmod 755 /app/entrypoint.sh \
    && infisical --version

USER gymu
EXPOSE 8000

# The deployment Compose file selects /app/entrypoint.sh.

# Test image: add development dependencies without shipping them in production.
FROM dependencies AS test

RUN uv sync --locked --no-install-project
COPY . .

CMD ["pytest", "-q"]

# Keep the production image as the default final target for CI builds.
FROM runtime AS production
