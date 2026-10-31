# Architecture

SEO Engine is a **modular monolith** (ADR-0001): one deployable application,
internally divided into domains that talk through typed interfaces, not a
constellation of microservices. The Build Specification is explicit that
premature microservices and premature scale-out are mistakes to avoid
(Rules 16–17); this document explains the shape that choice produced.

## The core loop

Everything the platform does serves one loop:

```
BRAND → WEBSITE → CRAWL → OBSERVE → RESEARCH → ANALYSE → OPPORTUNITY →
PRIORITISE → RECOMMEND → APPROVE → ACT → MEASURE → LEARN → MEMORY → REPEAT
```

A **mission** is a persistent objective pointed at that loop — the canonical one
is *"Increase qualified organic leads."* A mission is planned into a task graph,
each task runs one agent through the Agent Runtime, and the results flow forward
as evidence until the loop closes on a measured outcome.

## Layers

```
            ┌─────────────────────────────────────────────┐
  HTTP      │  apps/api  — FastAPI: auth, envelope, routes  │
            └───────────────┬─────────────────────────────┘
                            │ (no agent logic, no SQL)
            ┌───────────────▼─────────────────────────────┐
  Workflow  │  workflows — plan a mission, run its graph    │
            │  engine: local (in-process) or Temporal       │
            └───────────────┬─────────────────────────────┘
                            │
            ┌───────────────▼─────────────────────────────┐
  Agents    │  agent-runtime — the ONE path an agent runs:  │
            │  load → validate caps → build context →       │
            │  resolve perms/memory/tools → execute →       │
            │  validate result → persist → emit             │
            └───────────────┬─────────────────────────────┘
                            │ (agents call services, never the DB)
            ┌───────────────▼─────────────────────────────┐
  Domain    │  domain services — brands, websites, search,  │
            │  missions, decisions, integrations, identity  │
            └───────────────┬─────────────────────────────┘
                            │ (every query tenant-scoped)
            ┌───────────────▼─────────────────────────────┐
  Data      │  PostgreSQL 16 + pgvector, Redis              │
            └───────────────────────────────────────────────┘

  engines   deterministic SEO logic (crawler, checks, scoring,
            keywords, competitors, content) — pure functions over
            observed data, callable from any agent.
```

### Why the API carries no logic

Routes authenticate, authorise, call a domain service or dispatch work, and wrap
the result in the response envelope. They contain no agent logic and no SQL
(Build Spec rule 2). This keeps the consequential behaviour — tenancy, policy,
approvals, audit — in one tested place, below the transport, where it holds
regardless of how a request arrived.

### The Agent Runtime is the only way an agent runs

No route, workflow or other agent executes an agent's code directly. The runner
enforces a fixed lifecycle and calls the `ResultValidator` on every result. The
validator was written *before* any agent existed, so no agent can be written
that bypasses it. It enforces the invariants that matter: evidence-or-hypothesis
(Rule 7), no exposed chain-of-thought (Rule 8), no fabricated external metrics
(Rule 14), approval for high-risk items, and that an agent may only propose
actions its manifest declares.

### Engines are deterministic

SEO analysis that can be deterministic is deterministic (Rule 11). The crawler,
the technical checks, scoring, the keyword pipeline, competitor comparison and
content-gap decisions are pure functions over observed data. An agent's
contribution is to *interpret* and *sequence* their output, never to invent it.
The `ModelGateway`'s deterministic provider refuses rather than fabricating
prose, so an offline or model-less deployment degrades honestly.

## The monorepo

All Python lives under one implicit `seo_engine.*` namespace package assembled
from many roots under `packages/` and `apps/` (ADR-0001). The physical layout
mirrors the Build Specification's directory structure. The roots are wired
together by hatchling's `packages` + `dev-mode-dirs` in `pyproject.toml`, and
listed on the pytest path.

| Root | Contains |
| --- | --- |
| `packages/shared` | config, db, errors, security, ids, the untrusted-content boundary, the CLI |
| `packages/schemas` | every Pydantic v2 contract and the enums |
| `packages/domain` | ORM models, tenant-scoped repositories, domain services, the demo seed |
| `packages/engines` | deterministic SEO engines |
| `packages/agent-runtime` | the runner, validator, context builder, resolvers |
| `packages/agent-registry` | manifest loading and agent instantiation |
| `packages/workflows` | mission workflow, local and Temporal engines |
| `packages/memory`, `knowledge`, `evidence`, `events`, `policies`, `permissions`, `prompts`, `observability`, `integrations` | the supporting subsystems |
| `apps/api` | the FastAPI application |
| `apps/worker` | the worker process |
| `agents/` | the agent manifests, prompts, implementations and docs |

## Tenant isolation

Isolation exists in three layers, by design redundant (ADR and the security
tests):

1. a schema mixin puts a non-nullable `tenant_id` on every owned table;
2. the `TenantScopedRepository` predicates every query on the tenant and refuses
   to reassign `tenant_id` or rebind its session;
3. a session `before_flush` guard raises `TenantIsolationError` if any dirty row
   carries the wrong tenant.

The one hand-written SQL path — semantic memory search — re-asserts the tenant
predicate on both joined tables, because that is exactly where an isolation bug
would hide.

## Trust boundary

External website content is untrusted data (Rule 9). The `UntrustedContent`
type fences crawled copy with a per-render nonce and scans for injection
patterns; the context builder keeps SYSTEM, DEVELOPER_POLICY, USER, TOOL_OUTPUT
and EXTERNAL_CONTENT in separate channels that are never concatenated. Crawled
text is persisted by reference, not pasted into the platform's own tables, and
an injection attempt becomes a security finding rather than an instruction.

## Provenance

Every metric carries a `DataProvenance` label: observed, estimated, inferred,
user-provided, synthetic-demo or unknown. A figure the platform could not
measure stays `None` with `provenance=unknown`; it is never silently replaced by
an estimate. Development-mode integration adapters label everything they produce
synthetic. This is what lets the product show real numbers without ever lying
about which ones are real (Rules 1, 2, 14).

See `docs/architecture/decisions.md` for the numbered ADRs and
`docs/architecture/build-status.md` for a per-phase account of what exists.
