FROM ghcr.io/astral-sh/uv:0.9.8 AS uv
FROM infisical/cli:0.45.8 AS infisical
FROM python:3.14-slim AS runtime
COPY --from=uv /uv /uvx /bin/
COPY --from=infisical /bin/infisical /usr/local/bin/infisical
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 UV_COMPILE_BYTECODE=1 PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY . .
RUN infisical --version \
    && useradd --uid 10001 --create-home gymu \
    && mkdir -p /app/data/member-photos /app/staticfiles \
    && chown -R gymu:gymu /app/data /app/staticfiles \
    && chmod 755 /app/entrypoint.sh
USER gymu
EXPOSE 8000

FROM python:3.14-slim AS test
COPY --from=uv /uv /uvx /bin/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project
COPY . .
CMD ["pytest", "-q"]

FROM runtime AS production
