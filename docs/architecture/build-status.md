# Build status

An honest, per-phase account of the SEO Engine build. Nothing in this document
is aspirational: a phase is "done" only if it runs and is covered by a test that
passes against the real PostgreSQL + pgvector database.

Last updated: 2026-11-01.

---

## Summary

The agentic operating system is built and runs end to end. The canonical
mission — *"Increase qualified organic leads"* — plans a task graph, executes
each stage through the Agent Runtime against a real crawl, measures a baseline,
and produces evidence-backed, approval-gated recommendations. This is covered by
`tests/integration/test_mission_workflow.py`, which runs the real orchestrator,
runtime, crawler, engines and database with nothing mocked but the network.

All **36 MVP agents** named by the build prompt are implemented and wired into
mission graphs. **433 tests pass** (unit, integration, security, agent, workflow
and migration), `ruff` is clean, `mypy` reports no issues across 128 source
files, and the API,
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
| 22 | Test suites | **Done** — unit, integration, security, agent, workflow, migration (433 tests) |
| 23 | Security hardening | **Done** — isolation, injection boundary, no-fabrication, chain-of-thought and approval all enforced and tested |
| 24 | Documentation and QA gate | **Done** — the docs, `docs/api`, per-agent docs, and `make gate` (lint + typecheck + full suite, all green) |

---

## The MVP agents

All 36 agents are implemented, each with a manifest, implementation, schemas,
prompt, README and behavioural tests (see [`AGENTS.md`](../../AGENTS.md) for the
table). The orchestrator selects which a mission needs and records why every
omitted stage was omitted:

- **qualified leads** runs 24 stages: brand, objectives and profile; the crawl and
  indexability; Search Console, GA4 and the demand landscape; keyword, SERP,
  on-page, intent, architecture and question research; competitor discovery,
  analysis and gaps; content gaps; opportunities, prioritisation, the decision
  gate, the quality and policy guardians, and the execution plan;
- **content production** runs research → strategy → research packs → briefs →
  drafts → evaluation → optimisation → quality gate → policy review →
  repurposing → publishing;
- the other mission types run the subsets they need.

Analysis agents hand their findings to opportunity detection as evidenced seeds;
a seed with no evidence is refused. Stages have hard dependencies (`depends_on`)
and ordering-only ones (`after`), so a stage that merely benefits from SERP data
still runs, and says so, when SERP is not connected.

---

## Honest gaps

- **Production integration credentials** are not bundled (they must not be):
  without them Search Console, GA4 and the SERP API run their development
  adapters, which are labelled synthetic throughout. Synthetic SERP domains
  (`*.example`) are never proposed as competitors and a gap resting only on
  synthetic SERP data never becomes an opportunity. The production adapters are
  implemented and tested against in-process fakes.
- **Without a language model the content writer produces outlines, not prose.**
  The quality gate blocks outlines, so in a model-less deployment the content
  pipeline stops, by design, at a tracked "outline needs prose" repair. Nothing
  is ever published from an outline.
- **Content is approved through the API** (`POST /content/{id}/approve`). The web
  application lists agents, missions and recommendations, but has no dedicated
  content-review screen yet.
- **Publishing** goes through the brand's connected CMS adapter. The WordPress
  adapter is implemented; with the development CMS adapter, publication is
  recorded in `development_adapter` mode and reaches no real site.
- The **agent evaluation golden datasets** referenced by some agent READMEs are
  a growing set; the behavioural assertions live in the agent and integration
  tests today.
