# Deployment

SEO Engine is a modular monolith: one application image that runs as two process
types — the **API** and the **worker** — plus PostgreSQL (with pgvector), Redis
and, optionally, Temporal. It is designed to scale by running more of a process
type, not by splitting the application (Build Spec §83).

## Processes

| Process | Command | Responsibility |
| --- | --- | --- |
| API | `uvicorn seo_engine.api.main:app` (or `seo-engine serve`) | HTTP: auth, the domain surface, dispatching work |
| Worker | `python -m seo_engine.worker` | the Temporal worker (when enabled) and the periodic expired-memory sweep |

With `WORKFLOW_ENGINE=local` (the default) missions run in-process in the API,
and the worker only performs maintenance. With `WORKFLOW_ENGINE=temporal` the
worker hosts the mission workflow and its activities, and the API submits
workflows to the Temporal cluster. The engine never silently falls back: if
Temporal is configured but unreachable, the API raises a `ConfigurationError`
rather than quietly running missions locally, because a caller who asked for
durable orchestration must not be told they got it when they did not.

## Configuration

Everything is read once into the typed `Settings` object; nothing reads
`os.environ` directly. Copy `.env.example` to `.env` and populate it. The
variables that matter in production:

| Variable | Notes |
| --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://…`; the sync driver is derived for Alembic. |
| `REDIS_URL` | — |
| `WORKFLOW_ENGINE` | `local` or `temporal`. |
| `TEMPORAL_ADDRESS` / `_NAMESPACE` / `_TASK_QUEUE` | required when `temporal`. |
| `JWT_SECRET` | **must** be a strong random value; generate with `python -c "import secrets;print(secrets.token_urlsafe(48))"`. |
| `CREDENTIAL_ENCRYPTION_KEY` | Fernet key protecting stored OAuth tokens and API keys; generate with `Fernet.generate_key()`. |
| `LLM_PROVIDER` / `LLM_MODEL` / `LLM_BASE_URL` / `LLM_API_KEY` | Optional. `deterministic` (default) runs everything with no model. To connect any model: `openai_compatible` with the endpoint in `LLM_BASE_URL` (hosted or local; a key only if it needs one), or `anthropic` with a key. `LLM_MODEL` names the model and is required with any provider; there is no default. A model that fails never stops the platform; `/readyz` reports what is in use. |
| `LLM_TEMPERATURE` / `LLM_*_PRICE_PER_MTOK` | Optional. Unset sends no temperature (the model's default applies) and records call cost as unknown rather than zero. |
| `GOOGLE_CLIENT_ID` / `_SECRET` | enable the real Search Console and GA4 OAuth flow; without them those integrations run in development mode. |
| `API_CORS_ORIGINS` | comma-separated allowed origins for the web app. |
| `ENVIRONMENT` | `production` tightens defaults. |

Never commit populated values (Build Spec §73). In production, inject them from
your orchestrator's secret store, not a file on disk.

## Database

Migrations are the Alembic chain under `database/migrations/`, authored one
domain at a time. On deploy:

```bash
python -m alembic upgrade head    # or: seo-engine migrate
```

The first migration creates the `vector` and `pgcrypto` extensions, so the
database role needs permission to `CREATE EXTENSION` (the `pgvector/pgvector`
image already has the extension available). The migration tests assert that the
schema matches the ORM metadata, so a drift between the two is caught before
deploy.

## Docker

The provided `Dockerfile` builds the API/worker image as a non-root user; the
`docker-compose.yml` is a development stack, not a production topology. For
production, run the same image with your own orchestration: the API behind a
load balancer, the worker scaled to your workflow volume, managed PostgreSQL and
Redis, and Temporal if you use it.

```
          Load balancer
               │
        ┌──────┴──────┐
      Next.js        API ──── Redis
                      │
                 ┌────┴────┐
              Workers   Temporal
                 │
          PostgreSQL + pgvector
```

## Scaling

Scale the process that is busy, not the whole application (Rule 17, §83). The
worker is where crawls, research and execution run, so that is what scales with
mission volume; the API scales with request traffic. The database is the system
of record; add read replicas before sharding, and do neither until the numbers
demand it.

## Health

- `GET /healthz` — the process is up.
- `GET /readyz` — the process can serve: the database answers. Use this as the
  container readiness probe (the compose file does).

## Observability

Structured JSON logs carry the `request_id` and `correlation_id`, so a user-
visible request id ties a report straight to the exact run, agent and events
behind it. Counters and latencies are emitted for agent runs and failures.

## Pre-flight checklist

- [ ] `JWT_SECRET` and `CREDENTIAL_ENCRYPTION_KEY` set to strong random values
- [ ] `DATABASE_URL` points at managed PostgreSQL 16 with `pgvector` available
- [ ] migrations applied (`seo-engine migrate`)
- [ ] `ENVIRONMENT=production`, `API_CORS_ORIGINS` set to the real web origin
- [ ] `WORKFLOW_ENGINE` matches whether Temporal is actually running
- [ ] the quality gate (`make gate`) is green on the deployed commit
