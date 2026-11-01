# SEO Engine

An agentic search, content and growth operating system.

SEO Engine is **not a chatbot with SEO prompts**. The conversational surface is
one interface onto an agentic operating system whose core loop is:

```
BRAND → WEBSITE → CRAWL → OBSERVE → RESEARCH → ANALYSE → OPPORTUNITY →
PRIORITISE → RECOMMEND → APPROVE → ACT → MEASURE → LEARN → MEMORY → REPEAT
```

> **Build status:** the agentic operating system is built, with all 36 MVP
> agents. The canonical mission plans a dependency-ordered task graph, executes
> each stage through the Agent Runtime against a real crawl, measures a baseline,
> and produces evidence-backed, approval-gated recommendations; a content mission
> runs research → brief → draft → evaluation → quality gate → policy review →
> publishing, and nothing publishes without a person. 433 tests pass against a
> real PostgreSQL + pgvector database.
> See [`docs/architecture/build-status.md`](docs/architecture/build-status.md)
> for a precise, per-phase account.

---

## What is implemented and verified today

| Area | State | Verification |
| --- | --- | --- |
| Monorepo, tooling, `.env.example`, Docker stack, Makefile, `seo-engine` CLI | Done | `make install`, `docker compose config` |
| Typed configuration (`Settings`) | Done | every module reads it; no stray `os.environ` |
| PostgreSQL schema: **85 tables** across 11 domains + Alembic chain | Done | schema matches the ORM metadata (tested) |
| Three-layer tenant isolation | Done | security tests: cross-tenant read/write and the HTTP boundary |
| Prompt-injection trust boundary (`UntrustedContent`) | Done | security tests over the specification's attack strings |
| Agent Runtime + registry + result validator | Done | agent tests; the validator was written before any agent |
| Deterministic engines (crawler, checks, scoring, keywords, competitors, content) | Done | unit + integration tests against an in-process site |
| GSC / GA4 / SERP / CMS integrations (production + labelled development adapters) | Done | integration tests against in-process fake providers |
| Opportunity → prioritisation → decision → execution stack | Done | integration + the end-to-end mission |
| Mission workflow + local and Temporal engines | Done | the end-to-end mission test |
| FastAPI application (58 paths, one envelope) + worker | Done | 15 API tests through the real ASGI app |
| 36 MVP agents with manifest, impl, schemas, prompt, README and behavioural tests | Done | registry + catalogue tests; every agent but the planner runs in a mission graph |
| Content pipeline with human-only approval and gated publishing | Done | content agent tests: outlines never publish; approval and publish action both required |

A metric the platform cannot measure is `null` with honest provenance.
Development-mode integration data is labelled synthetic everywhere it appears.
There are no placeholder dashboards and no fabricated metrics.

## Quickstart

```bash
make install        # venv + editable install with dev/worker/llm extras
make migrate        # alembic upgrade head  (needs PostgreSQL 16 + pgvector)
make seed           # create the demonstration tenant
make run            # API at http://localhost:8000  (/docs for Swagger)
# or, the whole stack:
docker compose up
```

The canonical mission, end to end, is in
[`docs/api/walkthrough.md`](docs/api/walkthrough.md).

## Repository layout

```
apps/
  api/            FastAPI application            ✔
  worker/         Temporal worker + maintenance  ✔
  web/            Next.js product application    (in progress)

packages/
  shared/         config, errors, ids, db, untrusted-content boundary, CLI  ✔
  schemas/        every cross-cutting Pydantic contract                      ✔
  domain/         ORM models, tenant-scoped repositories, services, seed     ✔
  engines/        deterministic analysis engines                             ✔
  agent-registry/ agent-runtime/ orchestration/ workflows/ policies/
  permissions/ memory/ knowledge/ evidence/ events/ integrations/
  prompts/ observability/                                                    ✔

agents/           36 MVP agents (manifest, impl, schemas, prompt, docs)  ✔
database/
  migrations/     Alembic revisions 0001–0011                                ✔
  build_migrations.py  regenerates the domain-by-domain chain                ✔
  seed.py (seo_engine.database.seed)  the demonstration tenant               ✔
tests/
  unit/ integration/ security/ agent/                                        ✔
docs/
  api/            the HTTP contract, a walkthrough and example requests       ✔
  architecture/   ADRs and build status                                       ✔
  source-material/ the authoritative specifications this build follows        ✔
```

## Database domains

| Migration | Domain | Tables |
| --- | --- | --- |
| `0001_identity` | identity, tenancy, RBAC, commercial readiness | 7 |
| `0002_brands` | brand graph, competitors, projects | 11 |
| `0003_websites` | websites, crawl jobs, pages, links, images, schema, issues | 9 |
| `0004_search` | keywords, clusters, metrics, rankings, SERPs, intents, questions | 9 |
| `0005_content` | assets, versions, briefs, research, sources, evaluations, repurposing, repairs | 8 |
| `0006_agents` | agent catalogue, runs, messages, outputs, LLM usage | 7 |
| `0007_missions` | missions, tasks, dependencies, mission graph, metrics, progress | 6 |
| `0008_memory` | memories, pgvector embeddings, knowledge graph | 4 |
| `0009_decision` | evidence, opportunities, recommendations, actions, approvals, outcomes, experiments, policies | 9 |
| `0010_integrations` | connections, credentials, raw responses, GSC ×4, GA4 ×4 | 12 |
| `0011_events_audit` | event store, audit log | 2 |

Design rules enforced in the schema itself:

- every tenant-owned table carries a **non-nullable, indexed `tenant_id`**;
- raw provider responses live in `provider_raw_responses`, **separate** from the
  normalised `gsc_*` / `ga4_*` tables, so a normalisation bug can be replayed;
- every metric column that could be fabricated has a **`provenance`** column
  (`observed` / `estimated` / `inferred` / `user_provided` / `synthetic_demo` /
  `unknown`) — absent provider data stays `NULL` with `provenance='unknown'`;
- crawled page copy carries `is_untrusted_external_content` and
  `injection_findings`, so the untrusted marking survives into the agent layer;
- `content_versions` is append-only — previous versions are never overwritten;
- `actions` has a unique `(tenant_id, idempotency_key)` constraint.

## Local development

Prerequisites: Python 3.12+, PostgreSQL 16 with the `vector` extension, Redis.

```bash
# 1. Environment
cp .env.example .env          # then edit DATABASE_URL etc.

# 2. Install, migrate, seed
make install                  # venv + editable install (dev/worker/llm/storage)
make migrate                  # creates extensions + 85 tables
make seed                     # the demonstration tenant

# 3. Run
make run                      # API with reload; /docs for Swagger
make worker                   # the worker process (Temporal + maintenance)

# 4. Checks
make lint
make test                     # full suite (needs PostgreSQL + Redis)
```

Or the whole stack in containers:

```bash
docker compose up             # postgres, redis, temporal, api (migrated+seeded), worker, web
```

### Regenerating the migration chain

`database/build_migrations.py` rebuilds the whole chain from the ORM models, one
domain at a time, so the history stays readable. It is **destructive** to the
target database and is a developer tool only.

## Non-negotiable rules this build follows

These come from the Build Specification and the Agentic Architecture Pack and
are treated as invariants, not aspirations:

1. No fake integrations, no fabricated external data, no fake dashboards.
2. Agents run only through the Agent Runtime; API routes create tasks.
3. Agents reach data through domain services, never the database directly.
4. Every consequential action is policy-evaluated, approved and audited.
5. Every recommendation cites evidence or is explicitly a hypothesis —
   enforced by a validator written before any agent.
6. Chain of thought is never exposed or persisted; observations, evidence,
   conclusions, confidence and limitations are.
7. External content is `UNTRUSTED_EXTERNAL_CONTENT` and is never concatenated
   into the instruction stream.
8. Tenant isolation holds from the first migration.
9. Deterministic SEO analysis uses deterministic code, not an LLM.
10. No single opaque "SEO score" — nine visible dimensions.

## Documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md), [`AGENTS.md`](AGENTS.md),
  [`SECURITY.md`](SECURITY.md), [`INTEGRATIONS.md`](INTEGRATIONS.md),
  [`CONTRIBUTING.md`](CONTRIBUTING.md), [`DEPLOYMENT.md`](DEPLOYMENT.md).
- [`docs/api/`](docs/api/) — the HTTP contract, a walkthrough and example requests.
- [`docs/architecture/build-status.md`](docs/architecture/build-status.md) — the
  per-phase account of what is built.
- [`docs/architecture/decisions.md`](docs/architecture/decisions.md) — ADRs.
- [`docs/source-material/`](docs/source-material/) — the authoritative
  specifications and the supplied Google Search documentation.
