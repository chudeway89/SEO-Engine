# SEO Engine

An agentic search, content and growth operating system.

SEO Engine is **not a chatbot with SEO prompts**. The conversational surface is
one interface onto an agentic operating system whose core loop is:

```
BRAND → WEBSITE → CRAWL → OBSERVE → RESEARCH → ANALYSE → OPPORTUNITY →
PRIORITISE → RECOMMEND → APPROVE → ACT → MEASURE → LEARN → MEMORY → REPEAT
```

> **Build status:** this repository currently contains the verified foundation
> (Phases 1–2 of the build plan): repository and tooling, the complete database
> schema with a migration history, the core typed contracts, and the
> prompt-injection trust boundary. The agent runtime, engines, integrations,
> API and web application are **not yet implemented**.
> See [`docs/architecture/build-status.md`](docs/architecture/build-status.md)
> for a precise, per-phase account of what exists and what does not.

---

## What is implemented and verified today

| Area | State | Verification |
| --- | --- | --- |
| Monorepo layout, `uv`/`pnpm` tooling, `.env.example` | Done | `uv pip install -e ".[dev]"` |
| Typed configuration (`Settings`) | Done | imported by every module; no `os.environ` reads elsewhere |
| Domain error hierarchy → API error contract | Done | unit tests |
| Core Pydantic v2 contracts (agent manifest/context/result, evidence, crawl, SEO, search, content, events, API envelope) | Done | 21 contract tests |
| PostgreSQL schema: **75 tables** across 11 domains | Done | applied to PostgreSQL 16 |
| Alembic migration chain `0001_identity` … `0011_events_audit` | Done | clean `upgrade head` on an empty DB, clean `downgrade base` |
| pgvector-backed memory tables | Done | extension created by `0001`, `VECTOR(384)` column live |
| Tenant isolation primitives (`TenantOwnedMixin`, session flush guard) | Done | integration test asserts cross-tenant write raises `TenantIsolationError` |
| Prompt-injection trust boundary (`UntrustedContent`) | Done | 8 security tests covering the attack strings named in the specification |

Everything else in the specification is **not built yet** and is not stubbed,
mocked or faked. There are no placeholder dashboards and no fabricated metrics.

## Repository layout

```
apps/
  api/            FastAPI application            (not yet implemented)
  worker/         Temporal worker                (not yet implemented)
  web/            Next.js product application    (not yet implemented)

packages/
  shared/         config, errors, ids, db engine, untrusted-content boundary  ✔
  schemas/        every cross-cutting Pydantic contract                        ✔
  domain/         ORM models + domain services   (models ✔, services pending)
  engines/        deterministic analysis engines (pending)
  agent-registry/ agent-runtime/ orchestration/ workflows/ policies/
  permissions/ memory/ knowledge/ evidence/ events/ integrations/
  prompts/ observability/                        (pending)

agents/           35 MVP agents                  (pending)
integrations/     provider connector docs        (pending)
database/
  migrations/     Alembic revisions 0001–0011                                  ✔
  build_migrations.py  regenerates the domain-by-domain chain                  ✔
tests/
  unit/ integration/ security/                                                 ✔
  agent/ workflow/ evaluation/                   (pending)
docs/
  architecture/   ADRs and build status                                        ✔
  source-material/ the authoritative specifications this build follows         ✔
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

# 2. Python toolchain
uv venv --python 3.12 .venv
uv pip install --python .venv -e ".[dev,worker,llm]"

# 3. Database
createdb seo_engine
.venv/bin/python -m alembic upgrade head     # creates extensions + 75 tables

# 4. Checks
.venv/bin/python -m ruff check .
.venv/bin/python -m pytest -q
```

`docker compose up` is not yet available — the compose file lands with the API
and worker applications.

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
   enforced by a validator on `ProposedRecommendation`.
6. Chain of thought is never exposed or persisted; observations, evidence,
   conclusions, confidence and limitations are.
7. External content is `UNTRUSTED_EXTERNAL_CONTENT` and is never concatenated
   into the instruction stream.
8. Tenant isolation holds from the first migration.
9. Deterministic SEO analysis uses deterministic code, not an LLM.
10. No single opaque "SEO score" — nine visible dimensions.

## Documentation

- [`docs/architecture/build-status.md`](docs/architecture/build-status.md) — what
  is built, what is not, and what the next engineering phase is.
- [`docs/architecture/decisions.md`](docs/architecture/decisions.md) — ADRs.
- [`docs/source-material/`](docs/source-material/) — the authoritative
  specifications and the supplied Google Search documentation.
