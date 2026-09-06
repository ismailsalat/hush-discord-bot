# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base

# postgresql-client provides pg_dump, which the backup system shells out to.
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client tini \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so code changes do not invalidate the dependency layer.
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    "discord.py>=2.4" \
    "SQLAlchemy[asyncio]>=2.0" \
    "asyncpg>=0.29" \
    "aiosqlite>=0.20" \
    "alembic>=1.13" \
    "pydantic>=2.7" \
    "pydantic-settings>=2.3" \
    "structlog>=24.1"

COPY app ./app
COPY migrations ./migrations
COPY scripts ./scripts
COPY alembic.ini ./

# Never run as root.
RUN useradd --create-home --uid 10001 hush \
    && mkdir -p /data/backups /data/exports /data/logs \
    && chown -R hush:hush /app /data
USER hush

ENV BACKUP_DIRECTORY=/data/backups \
    EXPORT_DIRECTORY=/data/exports \
    LOG_DIRECTORY=/data/logs

HEALTHCHECK --interval=60s --timeout=15s --start-period=45s --retries=3 \
    CMD python scripts/health_check.py || exit 1

ENTRYPOINT ["tini", "--"]
CMD ["python", "-m", "app.main"]
