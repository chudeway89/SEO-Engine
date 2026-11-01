# Build status

An honest, per-phase account of the SEO Engine build. Nothing in this document
is aspirational: a phase is "done" only if it runs and is covered by a test that
passes against the real PostgreSQL + pgvector database.

Last updated: 2026-10-31.

---

## Summary

The agentic operating system is built and runs end to end. The canonical
mission — *"Increase qualified organic leads"* — plans a task graph, executes
each stage through the Agent Runtime against a real crawl, measures a baseline,
and produces evidence-backed, approval-gated recommendations. This is covered by
`tests/integration/test_mission_workflow.py`, which runs the real orchestrator,
runtime, crawler, engines and database with nothing mocked but the network.

**345 tests pass** (unit, integration, security, agent, workflow and migration),
`ruff` is clean, `mypy` reports no issues across 106 source files, and the API,
worker, Docker stack, seed and operator CLI exist. The Next.js web application is
built and was verified end to end through a real browser.

What has deliberately *not* happened, throughout: no placeholder UI, no mocked
dashboards, no fabricated metrics, no empty agent directories created to look
like coverage. A metric the platform cannot measure is `null` with honest
provenance; development-mode integration data is labelled synthetic everywhere
it appears.

---

## Phase-by-phase

| Phase | Scope | State |
| --- | --- | --- |
| 1 | Repository and infrastructure | **Done** — monorepo, tooling, `.env.example`, `docker-compose.yml`, Dockerfile, Makefile |
| 2 | Database and migrations | **Done** — 85 tables, 11 revisions, schema matches the ORM metadata (tested) |
| 3 | Authentication and tenancy | **Done** — JWT provider abstraction, RBAC, three-layer tenant isolation |
| 4 | Domain models and services | **Done** — ORM models, tenant-scoped repositories, domain services for every area |
| 5 | Agent Registry and Agent Runtime | **Done** — registry, the fixed lifecycle runner, resolvers, and the result validator written before any agent |
| 6 | Task and event systems | **Done** — the mission task graph with dependency edges, the event bus |
| 7 | Memory and evidence | **Done** — pgvector-backed memory with a deterministic embedder, the evidence collector |
| 8 | Website crawler | **Done** — robots, sitemap, fetch, parse, the untrusted-content boundary |
| 9 | Technical SEO engine | **Done** — deterministic checks across nine dimensions, scorecard, readiness |
| 10–13 | Research, keyword, competitor, content engines | **Done** — keyword pipeline, intent, clustering, competitor comparison, content-gap decisions |
| 14–15 | GSC and GA4 integrations | **Done** — production adapters (tested against an in-process fake Google) and labelled development adapters |
| 16 | Opportunity and recommendation engine | **Done** — detection from observations, the internal prioritisation model, the decision gate |
| 17 | Policy and approval engine | **Done** — rule evaluation, the automation-policy deferral, the approval matrix |
| 18 | Action execution framework | **Done** — policy-gated actions, draft-first CMS, outcome records |
| 19 | Workflows | **Done** — the mission workflow, the local engine, and the Temporal engine + worker |
| 20 | Web application | **Done** — a Next.js app, built and verified end to end through a real browser |
| 21 | End-to-end mission | **Done** — the canonical mission runs and is asserted end to end |
| 22 | Test suites | **Done** — unit, integration, security, agent, workflow, migration (345 tests) |
| 23 | Security hardening | **Done** — isolation, injection boundary, no-fabrication, chain-of-thought and approval all enforced and tested |
| 24 | Documentation and QA gate | **Done** — the docs, `docs/api`, per-agent docs, and `make gate` (lint + typecheck + full suite, all green) |

---

## The MVP agents

Eleven agents are implemented, each with a manifest, implementation, schemas,
prompt, README and behavioural tests: BRD-001, SEO-001, SEO-003, SEO-006,
CMP-002, ANA-001, ANA-002, OPP-001, PRI-001, DEC-001, EXE-001. The orchestrator
selects which a given mission needs rather than running all of them, and records
why each omitted stage was omitted. More agents from the full catalogue can be
added behind the same runtime; the eleven here are the set the canonical mission
exercises.

---

## Honest gaps

- **Production integration credentials** are not bundled (they must not be):
  without them the Google integrations run in development-adapter mode, which is
  labelled synthetic throughout. The production adapters are implemented and
  tested against an in-process fake Google.
- The **agent evaluation golden datasets** referenced by some agent READMEs are
  a growing set; the behavioural assertions live in the agent and integration
  tests today.
- The **full agent catalogue** is larger than the eleven MVP agents built here;
  the eleven are the set the canonical mission exercises, and more plug in behind
  the same runtime without new infrastructure.
