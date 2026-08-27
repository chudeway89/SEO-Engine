# SEO Engine — Sprint 0 / Sprint 1 Engineering Backlog v1.0

## Sprint 0 — Engineering Foundation

### Objective

Create a stable and secure development foundation.

Sprint 0 ends when:
- repository works locally
- infrastructure boots
- database migrations run
- authentication works
- tenant isolation passes
- brand and mission objects work
- Temporal worker executes
- observability works
- CI passes

---

## Epic S0.1 — Repository Foundation

### S0-001 — Initialise Monorepo
**Priority:** P0  
**Dependencies:** None

Create:
- apps/web
- apps/api
- apps/worker
- packages
- agents
- integrations
- database
- prompts
- tests
- docs
- infra

Configure:
- pnpm
- uv
- formatting
- linting
- strict TypeScript
- Git ignore
- environment management

**Acceptance Criteria**
- frontend boots
- backend boots
- worker boots
- dependencies install
- no secrets committed

### S0-002 — Code Quality Tooling
Configure:
- ESLint
- Prettier
- TypeScript strict
- Ruff
- mypy/pyright
- pytest

**Acceptance Criteria**
All lint/typecheck/test commands succeed.

---

## Epic S0.2 — Local Infrastructure

### S0-003 — Docker Development Environment
Services:
- postgres
- redis
- temporal
- temporal-ui
- api
- worker
- web

**Acceptance Criteria**
`docker compose up` starts complete environment.

### S0-004 — PostgreSQL + pgvector
- configure Postgres
- enable pgvector
- test DB
- migrations

### S0-005 — Redis
Use for:
- caching
- rate limits
- ephemeral coordination

### S0-006 — Temporal
Create sample SystemHealthWorkflow.

**Acceptance Criteria**
Workflow starts from API, runs via worker, persists, appears in Temporal UI.

---

## Epic S0.3 — Configuration & Secrets

### S0-007 — Environment Configuration
Create `.env.example` with:
- DATABASE_URL
- REDIS_URL
- TEMPORAL_ADDRESS
- TEMPORAL_NAMESPACE
- JWT_SECRET
- LLM_PROVIDER
- LLM_API_KEY
- GOOGLE_CLIENT_ID
- GOOGLE_CLIENT_SECRET
- GSC_SCOPES
- GA4_SCOPES
- AHREFS_API_KEY
- SEMRUSH_API_KEY
- S3 settings

---

## Epic S0.4 — Identity & Tenancy

### S0-008 — Tenant Schema
Create:
- tenants
- users
- tenant_users
- roles

### S0-009 — Authentication
Implement:
- register
- login
- logout
- current user

### S0-010 — Tenant Context Middleware
Resolve:
- user_id
- tenant_id
- role
- permissions
- request_id

### S0-011 — Cross-Tenant Security Tests
Attempt cross-access against:
- brands
- websites
- missions
- tasks
- memory
- actions

**Acceptance Criteria**
Every cross-tenant request fails.

---

## Epic S0.5 — Core Domain

### S0-012 — Brand Domain
Create:
- brands
- brand_goals
- brand_services
- brand_products
- brand_audiences
- brand_locations
- brand_claims
- brand_voice_profiles
- brand_competitors

### S0-013 — Projects
Create `projects`.

### S0-014 — Missions
Create:
- missions
- mission_metrics
- mission_progress

Mission states:
- CREATED
- PLANNING
- ACTIVE
- MONITORING
- ADAPTING
- ACHIEVED
- PAUSED
- FAILED
- CANCELLED
- EXPIRED

---

## Epic S0.6 — Task System

### S0-015 — Task Schema
Create:
- tasks
- task_dependencies

States:
- PENDING
- READY
- RUNNING
- WAITING
- BLOCKED
- COMPLETED
- FAILED
- CANCELLED

### S0-016 — Task Dependency Resolver
Support DAG dependencies.

---

## Epic S0.7 — Events

### S0-017 — Event Store
Create `events`.

### S0-018 — Event Publisher
Implement:
- publish
- subscribe
- persist

Do not introduce Kafka yet.

---

## Epic S0.8 — Evidence & Audit

### S0-019 — Evidence Store
Create:
- evidence
- evidence_relationships

Types:
- OBSERVATION
- API_DATA
- CRAWL_RESULT
- SERP_RESULT
- DOCUMENT
- HUMAN_INPUT
- EXPERIMENT
- MODEL_INFERENCE

### S0-020 — Audit Log
Create append-oriented `audit_logs`.

---

## Epic S0.9 — LLM Infrastructure

### S0-021 — Model Gateway
Implement:
- generate
- generate_structured
- embed
- classify
- summarise

### S0-022 — Structured Outputs
Use Pydantic validation.

### S0-023 — LLM Usage Tracking
Create `llm_usage`.

Track provider, model, tokens, latency, estimated cost.

---

## Epic S0.10 — Security Foundation

### S0-024 — External Content Trust Boundary
Content classes:
- SYSTEM
- APPLICATION_POLICY
- USER_INPUT
- TOOL_OUTPUT
- UNTRUSTED_EXTERNAL_CONTENT

### S0-025 — Prompt Injection Tests
Test malicious external instructions.

### S0-026 — SSRF Protection
Reject:
- localhost
- private network ranges
- metadata endpoints
- unsafe redirects
- unsupported schemes

---

## Epic S0.11 — Observability

### S0-027 — Structured Logging
Support:
- request_id
- correlation_id
- workflow_id
- task_id
- agent_run_id
- tenant_id

### S0-028 — Health Endpoints
- /health
- /health/database
- /health/redis
- /health/temporal

---

## Epic S0.12 — CI

### S0-029 — CI Pipeline
Run:
- install
- lint
- typecheck
- unit tests
- migration validation
- security tests
- build

### Sprint 0 Exit Gate
Sprint 0 passes only when:
- Docker boots
- API/frontend respond
- Temporal works
- Postgres/pgvector work
- authentication works
- tenant isolation passes
- brand creation works
- mission creation works
- tasks/events/audit work
- LLM gateway works
- CI is green

---

# Sprint 1 — First Agentic SEO Vertical Slice

## Objective

At Sprint 1 completion, a user can:

```text
Create Brand
 ↓
Add Website
 ↓
Crawl
 ↓
Technical Audit
 ↓
Generate Evidence
 ↓
Detect Opportunities
 ↓
Prioritise
 ↓
Receive Recommendations
```

---

## Epic S1.1 — Agent Runtime

### S1-001 — Agent Base Contract
Implement:
- id
- version
- capabilities
- validate
- execute

### S1-002 — Agent Manifest
Each agent:
- README.md
- manifest.yaml
- prompt.md
- agent.py
- schemas.py
- tests/

### S1-003 — Agent Registry
Implement:
- register
- discover
- get
- list
- validate

### S1-004 — Agent Context Builder
Context:
- tenant
- brand
- mission
- task
- memory
- evidence
- tools
- permissions
- policies

### S1-005 — Tool Resolver
Only declared tools allowed.

### S1-006 — Permission Resolver
Levels:
- READ
- PROPOSE
- EXECUTE
- AUTONOMOUS
- DENY

### S1-007 — Agent Runner
Lifecycle:
- load
- validate
- context
- permissions
- memory
- tools
- execute
- validate
- persist
- event

### S1-008 — Agent Run Persistence
Create:
- agent_runs
- agent_outputs
- agent_messages

Do not persist hidden chain-of-thought.

---

## Epic S1.2 — Initial Agents

Implement:
- ORCH-001
- BRD-001
- SEO-001
- SEO-002
- SEO-012
- OPP-001
- PRI-001
- DEC-001
- QUAL-001
- POL-001

### S1-009 — BRD-001
Build verified BrandContext.

### S1-010 — ORCH-001
Create task graph for:
> Analyse this website and tell me what we should fix first.

Expected:
```text
Brand Context
 ↓
Website Crawl
 ↓
Technical SEO
 ↓
On-Page SEO
 ↓
Indexability
 ↓
Opportunity Detection
 ↓
Prioritisation
 ↓
Decision Review
```

---

## Epic S1.3 — Website Domain

### S1-011 — Website Schema
Create:
- websites
- crawl_jobs
- crawl_pages
- pages
- page_links
- page_images
- page_schema
- page_issues

### S1-012 — Website API
Implement:
- POST /brands/{brand_id}/websites
- GET /websites/{id}
- POST /websites/{id}/crawl
- GET /crawl-jobs/{id}
- GET /websites/{id}/pages
- GET /websites/{id}/issues

---

## Epic S1.4 — Crawler

### S1-013 — HTTP Crawler
Fetch and parse pages.

### S1-014 — robots.txt Parser

### S1-015 — Sitemap Discovery

### S1-016 — Crawl Frontier
Support:
- queue
- visited
- depth
- domain restrictions
- max pages
- rate limiting

### S1-017 — Playwright Fallback
Use only when necessary.

### S1-018 — Normalisation
Store:
- URL
- canonical
- title
- meta
- headings
- visible content
- links
- images
- schema
- robots
- status

---

## Epic S1.5 — Deterministic SEO

### S1-019 — Rule Framework
Create:
- Rule
- RuleResult
- Severity
- Evidence
- RecommendationTemplate

### S1-020 — Title Rules
Detect:
- missing
- duplicate
- empty
- boilerplate
- repetition
- main-title mismatch candidates

### S1-021 — Metadata Rules

### S1-022 — Heading Rules

### S1-023 — Indexability Rules
Detect:
- non-200
- noindex
- robots conflict
- canonical conflict
- redirects
- broken destination

### S1-024 — Internal Link Rules

### S1-025 — Image Rules

### S1-026 — Structured Data Inventory

---

## Epic S1.6 — SEO Agents

### S1-027 — SEO-001 Technical SEO Agent
Interpret technical findings.

### S1-028 — SEO-002 On-Page Agent
Analyse:
- title
- headings
- page topic
- content
- internal links

### S1-029 — SEO-012 Indexability Agent
Diagnose crawl/index issues.

---

## Epic S1.7 — Evidence

### S1-030 — Finding-to-Evidence Conversion

### S1-031 — Evidence Relationship Graph
Link evidence to:
- page
- issue
- opportunity
- recommendation
- task
- mission

---

## Epic S1.8 — Opportunity Engine

### S1-032 — Opportunity Object
Create `opportunities`.

### S1-033 — OPP-001
Convert findings into strategic opportunities.

---

## Epic S1.9 — Prioritisation

### S1-034 — Priority Model

```text
Priority =
Impact
× Confidence
× Strategic Fit
÷ Effort
```

### S1-035 — PRI-001
Consider:
- severity
- affected pages
- business relevance
- site-wide impact
- confidence
- effort

---

## Epic S1.10 — Decision Quality

### S1-036 — DEC-001
Challenge recommendations.

### S1-037 — QUAL-001
Reject:
- evidence-free claims
- ranking guarantees
- fake scores
- duplicate recommendations
- unsupported certainty

---

## Epic S1.11 — Policy

### S1-038 — Policy Schema

### S1-039 — POL-001
Evaluate recommendations and future action permissions.

---

## Epic S1.12 — First Mission Workflow

### S1-040 — WebsiteAuditWorkflow

```text
Load Brand
 ↓
Crawl
 ↓
Technical Rules
 ↓
SEO-001
 ↓
SEO-002
 ↓
SEO-012
 ↓
Evidence
 ↓
OPP-001
 ↓
PRI-001
 ↓
DEC-001
 ↓
QUAL-001
 ↓
Recommendations
```

### S1-041 — Mission API
- POST /missions
- POST /missions/{id}/run
- GET /missions/{id}
- GET /missions/{id}/tasks
- GET /missions/{id}/events

---

## Epic S1.13 — UI

### S1-042 — Application Shell
Navigation:
- Dashboard
- Brands
- Websites
- SEO Audit
- Opportunities
- Recommendations
- Missions
- Activity
- Settings

### S1-043 — Brand Onboarding

### S1-044 — Crawl UI

### S1-045 — Technical Audit UI

### S1-046 — Recommendation UI

Show:
- what
- why
- evidence
- affected pages
- impact
- effort
- risk
- confidence
- priority

### S1-047 — Agent Activity UI
Show operational events only, not hidden reasoning.

---

## Epic S1.14 — Testing

### S1-048 — Crawler Fixtures
Include:
- 200
- 404
- redirect
- noindex
- canonical
- duplicate title
- missing title
- missing H1
- broken link
- robots block
- JSON-LD

### S1-049 — SEO Rule Tests

### S1-050 — Agent Behaviour Tests

### S1-051 — Prompt Injection Test

### S1-052 — Workflow Recovery Test

### S1-053 — Tenant Security Regression

---

# Sprint 1 Exit Gate

The complete user journey must work without manual DB manipulation:

```text
Create account
 ↓
Create organisation
 ↓
Create brand
 ↓
Add website
 ↓
Create mission
 ↓
Orchestrator builds tasks
 ↓
Crawler runs
 ↓
SEO rules run
 ↓
Agents interpret findings
 ↓
Evidence persists
 ↓
Opportunity Agent creates opportunities
 ↓
Prioritisation ranks them
 ↓
Decision Agent reviews
 ↓
Quality Guardian validates
 ↓
User sees prioritised recommendations
```

---

# What Must Not Enter Sprint 1

Do not dilute Sprint 1 with:
- full Ahrefs integration
- full Semrush integration
- Google Ads execution
- GBP automation
- autonomous publishing
- billing
- white labelling
- advanced AI citation monitoring
- dozens of extra agents

Prove the core agentic SEO loop first.
