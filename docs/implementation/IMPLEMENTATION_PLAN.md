# Sprint 0 and Sprint 1 Implementation Plan

Statuses: `NOT STARTED`, `IN PROGRESS`, `PARTIAL`, `IMPLEMENTED`, `BLOCKED`.

| Task ID | Title | Dependencies | Files likely affected | Implementation approach | Acceptance criteria | Tests required | Status |
|---|---|---|---|---|---|---|---|
| S0-001/002 | Monorepo and quality tooling | None | `pyproject.toml`, `apps/*`, `packages/*` | Establish uv Python workspace, then pnpm web workspace and strict linters | all applications boot; lint/type/test pass | install, lint, typecheck, smoke | PARTIAL |
| S0-003—006 | Local infrastructure | S0-001 | `compose.yaml`, `infra/*`, `apps/worker/*` | Compose pgvector, Redis, Temporal, API, worker, web; health workflow | all services healthy and workflow visible | compose smoke and workflow integration | NOT STARTED |
| S0-007 | Environment configuration | S0-003 | `.env.example`, settings module | typed settings with safe defaults and secret validation | documented variables; no committed secret | configuration tests | NOT STARTED |
| S0-008—011 | Identity and tenancy | S0-004 | `seo_engine/core/*`, API routes, migrations | tenant-owned records, memberships/RBAC, signed auth, mandatory context | auth journey works and cross-tenant reads/writes fail | auth, RBAC, cross-tenant suite | PARTIAL |
| S0-012—014 | Core domains | S0-008 | domain models/services/migrations | brands, projects, mission lifecycle behind tenant service | CRUD and legal transitions work | service/API tests | PARTIAL |
| S0-015/016 | Task DAG | S0-014 | task domain and repository | reject cycles/self-dependency; readiness only after prerequisites | dependencies gate execution | DAG tests | PARTIAL |
| S0-017—020 | Events, evidence, audit | S0-004 | stores/migrations | append-oriented tenant-aware persistence | consequential changes emit immutable records | persistence/isolation tests | PARTIAL |
| S0-021—023 | LLM gateway | S0-007 | `seo_engine/llm/*` | provider interface, structured validation, usage accounting | provider can be substituted and usage retained | fake-provider contract tests | NOT STARTED |
| S0-024—026 | Trust boundary and SSRF | S0-001 | `seo_engine/security.py` | label external text as data; public HTTP(S) destination validation | private/metadata/unsafe destinations rejected | injection and SSRF tests | PARTIAL |
| S0-027—029 | Observability and CI | preceding S0 | logging, health routes, `.github/workflows/*` | structured correlation fields and full CI matrix | health checks truthful; CI green | health/dependency/CI tests | NOT STARTED |
| S1-001—008 | Common agent runtime | Sprint 0 gate | `seo_engine/agents/*` | manifest registry, resolvers, context, runner and safe run persistence | every agent uses canonical lifecycle | capability/permission/output tests | NOT STARTED |
| S1-009/010, S1-027—029, S1-033/035—039 | Initial agents | runtime | `agents/*` | deterministic inputs and structured outputs through runner only | required ten agents registered and governed | behaviour/guardian tests | NOT STARTED |
| S1-011—018 | Website and crawler | S0 gate | website/crawler modules | bounded HTTP crawl, robots/sitemap, normalized page graph, SSRF on every hop | real fixture site crawl with limits | fixture, redirect, robots, attack tests | NOT STARTED |
| S1-019—026 | Deterministic SEO | crawler | SEO rules | pure rules produce findings before interpretation | specified issue classes detected | rule fixtures | NOT STARTED |
| S1-030—041 | Evidence-to-recommendation workflow | agents/rules | workflow/domain/API | persist evidence, opportunities, priorities, reviews and recommendations | end-to-end mission works without DB manipulation | workflow recovery and tenant tests | NOT STARTED |
| S1-042—047 | Minimal web UI | APIs | `apps/web/*` | only specified working screens using query cache and schemas | user completes vertical slice and sees evidence | component/e2e/accessibility | NOT STARTED |
| S1-048—053 | Exit suite | all Sprint 1 | `tests/*` | adversarial and end-to-end fixtures | complete gate passes | full CI and compose e2e | NOT STARTED |

Tasks are executed in dependency order. A `PARTIAL` row is never interpreted as satisfying an exit gate.
