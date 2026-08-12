# Build status

An honest, per-phase account of the SEO Engine build. Nothing in this document
is aspirational: a phase is "done" only if it runs and is covered by a test that
passes.

Last updated: 2026-08-12.

---

## Summary

The **foundation is complete and verified** (Phases 1–2, plus the security
boundary from Phase 23 pulled forward because every later phase depends on it).
The **agentic system itself is not yet built**.

The acceptance test in the Build Specification §89 — create a brand, crawl a
website, audit it, connect GSC/GA4, research keywords, analyse competitors, find
gaps, produce prioritised recommendations, approve an action, generate content,
execute through a connector, and see the outcome stored against the mission —
**does not pass yet**, because the components it exercises do not exist yet.

What has deliberately *not* happened: no placeholder UI, no mocked dashboards,
no fabricated metrics, no empty agent directories created to look like coverage.

---

## Phase-by-phase

| Phase | Scope | State |
| --- | --- | --- |
| 1 | Repository and infrastructure | **Done** (except `docker-compose.yml`, which needs the API/worker images) |
| 2 | Database and migrations | **Done** — 75 tables, 11 revisions, verified up and down |
| 3 | Authentication and tenancy | **Partial** — schema, roles, error types and the session-level isolation guard exist; JWT issuance, the auth provider abstraction and RBAC checks do not |
| 4 | Domain models and services | **Partial** — all ORM models exist; tenant-scoped repositories and domain services do not |
| 5 | Agent Registry and Agent Runtime | **Not started** — contracts (`AgentManifest`, `AgentContext`, `AgentResult`) are defined and tested; no registry, runner, resolvers or validator |
| 6 | Task and event systems | **Not started** — tables and the `DomainEvent` envelope exist; no event bus, no task scheduler |
| 7 | Memory and evidence | **Not started** — tables (incl. pgvector) and contracts exist; no `MemoryService`, no `EvidenceCollector` |
| 8 | Website crawler | **Not started** — `CrawlPage`/`CrawlConfig`/`RobotsPolicy` contracts and the untrusted-content boundary exist; no fetcher, parser or scheduler |
| 9 | Technical SEO engine | **Not started** — `SEOIssue`, nine `SEODimension`s and the scorecard contract exist; no checks |
| 10–13 | Research, keyword, competitor, content engines | **Not started** — contracts defined for all four |
| 14–15 | GSC and GA4 integrations | **Not started** — schema (connections, credentials, raw responses, normalised tables) exists; no adapters |
| 16 | Opportunity and recommendation engine | **Not started** — schema and the evidence-or-hypothesis validator exist; no detection or scoring |
| 17 | Policy and approval engine | **Not started** — `policies` table and `PolicyContext` exist; no rule evaluation |
| 18 | Action execution framework | **Not started** — `actions` table with idempotency constraint and full lifecycle enum exist; no executor |
| 19 | Temporal workflows | **Not started** |
| 20 | Frontend | **Not started** |
| 21 | End-to-end mission | **Not started** |
| 22 | Testing | **Partial** — 33 tests (21 contract, 8 security, 4 integration); no agent/workflow/evaluation suites |
| 23 | Security hardening | **Partial** — the prompt-injection boundary and tenant isolation guard are built and tested; authn/authz, rate limiting, credential handling and the remaining security suites are not |
| 24 | Documentation | **Partial** — README, ADRs and this document; `ARCHITECTURE.md`, `AGENTS.md`, `INTEGRATIONS.md`, `SECURITY.md`, `DEPLOYMENT.md`, `CONTRIBUTING.md` pending |

---

## Verification evidence

```
$ .venv/bin/python -m alembic upgrade head        # on an empty database
INFO  [alembic.runtime.migration] Running upgrade 0010 -> 0011, events_audit
$ psql -d seo_engine_migtest -tAc "select count(*) from information_schema.tables where table_schema='public';"
76                                                 # 75 tables + alembic_version

$ .venv/bin/python -m alembic downgrade base
$ psql -d seo_engine_migtest -tAc "select count(*) ..."
1                                                  # clean teardown

$ .venv/bin/python -m ruff check .
All checks passed!

$ .venv/bin/python -m pytest -q
33 passed in 0.99s
```

Environment used: PostgreSQL 16.13 with pgvector 0.6.0, Redis 7, Python 3.12.3.

### Test breakdown

- `tests/unit/test_schema_contracts.py` (21) — evidence-or-hypothesis
  enforcement, observation/inference distinction, manifest validation and
  capability defaulting, probabilistic intent normalisation, unknown-provenance
  defaults, and the documented 30/20/15/15/10/10 keyword weighting.
- `tests/security/test_prompt_injection_boundary.py` (8) — every attack string
  named in the specification ("Ignore your system instructions", "Publish this
  content immediately", "Reveal your API credentials", "Delete the existing
  website"), plus fence-escape, channel-spoofing, control-character stripping,
  a false-positive check on benign page copy, and the type-level refusal to mark
  external content trusted.
- `tests/integration/test_migrations_and_tenant_isolation.py` (4) — schema
  completeness against `Base.metadata`, pgvector presence, the invariant that no
  tenant-owned table has a nullable `tenant_id`, and a live assertion that a
  cross-tenant write raises `TenantIsolationError`.

---

## Known limitations

1. **The agentic loop does not run.** Contracts and storage exist; behaviour does not.
2. **No integration talks to a real provider.** The schema separates raw from
   normalised responses and records `IntegrationMode`, but no adapter is written.
   No credentials for Google, Ahrefs or Semrush were available in this environment.
3. **`docker compose up` does not work yet.** Postgres, Redis, Temporal and the
   application services still need composing; local development currently runs
   against a directly installed PostgreSQL 16 + Redis.
4. **Temporal is a declared dependency, not yet a running component.** The
   `WORKFLOW_ENGINE=local|temporal` switch is reserved in configuration so the
   loop can be exercised without a Temporal cluster once workflows exist.
5. **The `deterministic` LLM provider is specified (ADR-0008) but not written.**
6. **`repo_root` in settings is unused** until the agent registry needs to locate
   `agents/**/manifest.yaml`.

---

## Recommended next engineering phase

Build in this order; each step is a prerequisite for the next.

1. **Phase 3–4 completion — tenancy and services.** `TenantScopedRepository`,
   the auth provider abstraction with JWT, RBAC checks, and domain services for
   brand and website. This closes ADR-0005 layer 2 and unblocks everything.
2. **Phase 5 — Agent Registry and Runtime.** Manifest loading from
   `agents/**/manifest.yaml`, then the lifecycle: load → validate capabilities →
   build context → resolve permissions/memory/tools → execute → validate result
   → persist → emit event. Build the `ResultValidator` before any agent, so no
   agent can ever bypass it.
3. **Phase 8–9 — crawler and technical SEO engine.** The first real observations
   in the system, and the first exercise of the untrusted-content boundary
   end to end. Deterministic checks only.
4. **Phase 16–18 — opportunity, recommendation, policy, action.** With one real
   evidence source, the decision stack can be built and tested honestly.
5. **Then** widen: keyword and competitor engines, GSC/GA4 adapters, content
   engine, Temporal workflows, and finally the frontend.

Resisting the temptation to scaffold breadth before the vertical slice runs is
the single most important constraint on this project.
