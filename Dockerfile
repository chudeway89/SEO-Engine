# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# SEO Engine — API and worker image.
#
# One image serves both processes; the compose file chooses the command. The
# build installs the namespace-package monorepo as an editable install so the
# many `seo_engine.*` roots resolve exactly as they do in development.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libpq for psycopg; curl for the container healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependency layer: copy only what pip needs to resolve, so edits to source do
# not invalidate the installed dependencies.
COPY pyproject.toml README.md ./
COPY packages ./packages
COPY apps ./apps
COPY agents ./agents
COPY database ./database
COPY alembic.ini ./

RUN pip install -e ".[worker,llm,storage]"

# A non-root runtime user: the process never needs to write to the image.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Overridden per service in docker-compose; this is the API default.
CMD ["uvicorn", "seo_engine.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
