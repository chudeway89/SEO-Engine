# SEO Engine — Product & Engineering Roadmap v1.0

## Roadmap Principle

The order is:

> **Intelligence before automation. Evidence before execution.**

SEO Engine should expand only after the core agentic loop is proven.

---

# Phase 0 — Engineering Foundation

## Objective
Create a secure, testable agentic platform foundation.

Build:
- monorepo
- Docker
- PostgreSQL
- pgvector
- Redis
- Temporal
- authentication
- tenancy
- RBAC
- task system
- events
- evidence store
- audit logs
- LLM gateway
- observability
- CI/CD baseline

## Exit Gate
Infrastructure works locally and in CI, tenant isolation is verified, missions/tasks/events exist.

---

# Phase 1 — Agent Runtime & Website Intelligence

## Objective
Prove SEO Engine is genuinely agentic.

Build:
- agent registry
- capability model
- permissions
- context builder
- agent runner
- crawler
- robots/sitemap parsing
- deterministic technical SEO
- on-page analysis
- indexability
- evidence engine
- opportunity engine
- prioritisation
- decision/quality guardians
- initial mission UI

## Exit Gate

```text
Brand
 ↓
Website
 ↓
Crawl
 ↓
Technical Analysis
 ↓
Evidence
 ↓
Opportunity
 ↓
Prioritisation
 ↓
Recommendation
```

works end-to-end.

---

# Phase 2 — Search Intelligence

## Objective
Connect real search and analytics data.

Build:
- Google Search Console
- GA4
- keyword engine
- search intent
- keyword clustering
- SERP research
- competitor intelligence
- content gaps
- query/page performance
- striking-distance keywords
- low-CTR opportunities
- conversion-linked SEO analysis

## Exit Gate
SEO Engine can explain:
- what is happening
- where the opportunity is
- what should be worked on next
- why

---

# Phase 3 — Content Intelligence

## Objective
Create an evidence-backed authoritative content system.

Build:
- content strategist
- source research
- research packs
- content briefs
- writer
- updater
- editor
- fact checker
- E-E-A-T review
- originality review
- content risk
- consolidator
- content inventory
- version history
- repurposing

## Core Decision

Before creation:

```text
CREATE
UPDATE
CONSOLIDATE
REDIRECT
DO NOTHING
```

## Exit Gate
The system can research, draft, review and improve authoritative content without fabricating evidence.

---

# Phase 4 — Execution & CMS

## Objective
Move from recommendation to controlled action.

Build:
- CMS provider abstraction
- WordPress integration
- generic CMS API
- GitHub-based content/site changes where appropriate
- metadata updates
- content drafts
- content publication
- internal links
- schema updates
- action approvals
- action logs
- rollback metadata
- sitemap actions

## Exit Gate

```text
Recommendation
 ↓
Approval
 ↓
Action
 ↓
Execution
 ↓
Audit
```

works reliably.

---

# Phase 5 — Measurement & Learning

## Objective
Close the loop.

Build:
- recommendation → action linkage
- baseline capture
- outcome windows
- SEO performance measurement
- conversion measurement
- action outcome records
- experiments
- learning engine
- historical memory
- outcome memory
- recommendation effectiveness analytics

## Exit Gate

```text
Recommendation
 ↓
Action
 ↓
Outcome
 ↓
Learning
```

is operational.

---

# Phase 6 — Local SEO

## Objective
Manage location-based visibility.

Build:
- Google Business Profile integration
- locations
- categories
- services
- hours
- local competitors
- reviews
- review sentiment
- review-response workflows
- location pages
- NAP/citation consistency
- local opportunity scoring

## Exit Gate
A multi-location business can receive local SEO recommendations and execute approved profile/content actions.

---

# Phase 7 — Paid Growth

## Objective
Connect organic search intelligence with paid acquisition.

Build:
- Google Ads integration
- paid keyword analysis
- campaign planner
- landing page analysis
- ad recommendations
- negative keywords
- budget guardian
- campaign approvals
- paid competitor intelligence
- organic + paid opportunity coordination

## Permissions
Initial:
- READ_ONLY
- RECOMMEND
- APPROVE_EACH_ACTION

Later:
- AUTO_EXECUTE_WITHIN_LIMITS

## Guardrails
- max daily spend
- max campaign spend
- max CPC
- max CPA
- geography
- approved campaigns
- allowed hours
- kill switch

---

# Phase 8 — Autonomous Monitoring

## Objective
Turn projects into persistent operations.

Build:
- recurring missions
- scheduled crawling
- analytics sync
- anomaly detection
- content decay detection
- competitor movement detection
- indexing alerts
- policy-driven auto-fixes
- automatic task creation
- approval queues

Example mission:

> Maintain technical SEO health and automatically resolve low-risk issues.

---

# Phase 9 — AI Search Visibility

## Objective
Measure and improve observable visibility in AI-powered search without relying on unverified ranking claims.

Build:
- AI citation tracking where observable
- brand mention monitoring
- URL citation monitoring
- entity associations
- question coverage
- competitor comparison
- AI-search readiness score based on observable/structural factors

Explicitly separate:
- observed
- inferred
- unknown

---

# Phase 10 — Agent Experience / Machine Discoverability

## Objective
Prepare websites for emerging browser agents and machine interaction.

Audit:
- semantic HTML
- accessibility tree
- form labels
- buttons
- navigation
- structured data
- machine-readable product/service data
- JavaScript dependence
- action discoverability
- booking/checkout interactions
- DOM clarity

Future product category expansion:

> Optimisation for humans, search engines and AI agents.

---

# Phase 11 — Commercial SaaS Readiness

## Objective
Turn the internal product into a scalable commercial platform.

Build:
- subscription plans
- entitlements
- usage tracking
- metering
- billing
- onboarding
- self-service integrations
- team roles
- agency hierarchy
- white labelling
- usage dashboards
- cost controls
- support tooling
- legal/compliance workflows

Possible plans:
- Starter
- Pro
- Growth
- Agency
- Enterprise

Entitlements may vary by:
- brands
- websites
- users
- crawl volume
- agent runs
- content generation
- integrations
- analytics history
- autonomous actions
- paid-media access

---

# Phase 12 — Enterprise & Scale

## Objective
Extract services only where operational scale requires it.

Potential worker/service extraction:
- crawl workers
- research workers
- content workers
- analytics workers
- agent workers
- execution workers

Potential infrastructure:
- managed Postgres
- managed Redis
- object storage
- container orchestration
- queue/event infrastructure
- OpenSearch where required
- dedicated analytics store

Do not introduce complexity before usage justifies it.

---

# Canonical Product Milestones

## Milestone A — Agentic Auditor
SEO Engine can understand a brand, crawl a site and prioritise what to fix.

## Milestone B — Search Intelligence System
SEO Engine knows what the brand should work on based on real search, competitor and conversion data.

## Milestone C — Content Intelligence System
SEO Engine can produce and improve authoritative content based on evidence.

## Milestone D — Execution System
SEO Engine can safely implement approved recommendations.

## Milestone E — Closed Learning Loop
SEO Engine measures outcomes and learns.

## Milestone F — Growth OS
SEO, Local and Paid Search operate together.

## Milestone G — Autonomous Growth Operations
Persistent missions continuously detect, prioritise and act within policy.

---

# North-Star Mission

The mature system should accept:

> **Grow qualified organic leads by 30% over six months.**

Then autonomously:

```text
understand business
 ↓
analyse website
 ↓
analyse market
 ↓
analyse competitors
 ↓
research search demand
 ↓
analyse existing content
 ↓
identify opportunities
 ↓
prioritise
 ↓
build strategy
 ↓
create work plan
 ↓
create/update content
 ↓
optimise website
 ↓
run approved paid experiments
 ↓
measure conversions
 ↓
learn
 ↓
adapt strategy
 ↓
continue
```

The human becomes the executive decision-maker rather than the task operator.
