# Contributing

## Setup

Requires Python 3.12, PostgreSQL 16 with the `pgvector` extension, and Redis.

```bash
make install        # create .venv and install -e ".[dev,worker,llm,storage]"
make migrate        # alembic upgrade head
make seed           # create the demonstration tenant
make run            # the API at http://localhost:8000 (/docs for Swagger)
```

Or bring the whole stack up in Docker:

```bash
docker compose up
```

which starts PostgreSQL, Redis, Temporal, the API (migrated and seeded), the
worker and the web app.

## The layout

All Python is one implicit `seo_engine.*` namespace package assembled from the
roots under `packages/` and `apps/` (see `ARCHITECTURE.md`). Put new code in the
root that owns its concern:

- a new **contract** → `packages/schemas`
- a new **domain operation** → a service in `packages/domain`
- new **deterministic SEO logic** → `packages/engines`
- a new **agent** → a directory under `agents/` (see `AGENTS.md`)
- a new **endpoint** → a router in `apps/api`

Agents never touch the database; they call domain services. Routes carry no
agent logic and no SQL. Deterministic analysis lives in engines, not in agents.

## The rules that are not negotiable

These are enforced, and a change that breaks one will fail tests or review:

- **No fabrication.** A metric the platform cannot measure stays `null` with
  honest provenance. Never invent search volume, difficulty, rankings,
  competitor metrics or AI-visibility figures.
- **Tenant isolation.** Every owned query goes through a tenant-scoped
  repository. Do not add a hand-written query without the tenant predicate.
- **The Agent Runtime is the only path an agent runs.** Do not call an agent's
  `execute` directly from a route, a workflow or another agent.
- **No chain-of-thought in output.** Expose conclusions, evidence and
  limitations, never private reasoning.
- **Approvals and policies are not bypassable.** A consequential action goes
  through policy evaluation and, where required, human approval.
- **Never commit secrets.** `.env` is ignored; use `.env.example` as the
  template.

## Code style

- `ruff` for lint and format, line length 100.
- `mypy` for types.
- Comments state constraints the code cannot show; they do not narrate.
- Match the surrounding code's idiom.

## Tests

The suite runs against a real PostgreSQL + pgvector database, not SQLite or
mocks, so behaviour is tested against the actual target. HTTP paths run through
in-process ASGI apps over httpx, so real status codes, redirects, headers and
auth execute without network access.

```bash
make test           # the full suite
make test-fast      # unit tests only, no database
make security       # the security regression tests
```

Categories (pytest markers): `integration`, `security`, `evaluation`. Agent
behaviour is tested behaviourally — the assertions check the properties in each
agent's README, not implementation details.

When something fails: diagnose it, find the root cause, fix it, test the fix,
and document it. Do not hide an error, fake a response, skip a test, comment out
a failing feature, or mark work complete that is not.

## The quality gate

Before a change is done, `make gate` must pass: lint, then the full suite
(unit, integration, security, workflow, migration and agent tests). The Build
Specification's gate (§80) additionally expects a clean `mypy` and the agent
evaluation suite.

## Commits and branches

- Work on a feature branch; never commit straight to the default branch.
- Write commit messages that explain *why*, not just *what*.
- Do not open a pull request unless it is explicitly asked for.
