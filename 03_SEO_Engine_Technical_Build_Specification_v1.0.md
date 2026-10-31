# SEO Engine — Technical Build Specification v1.0

## 1. Build Objective

Build the first working production-grade vertical slice of SEO Engine.

The system must support:

```text
Brand
 ↓
Website
 ↓
Crawl
 ↓
Research
 ↓
Analysis
 ↓
Opportunity
 ↓
Recommendation
 ↓
Approval
 ↓
Action
 ↓
Measurement
 ↓
Memory
```

A working vertical slice is more important than superficial breadth.

---

# 2. Technology Decisions

## Frontend
- Next.js
- TypeScript
- Tailwind CSS
- shadcn/ui
- TanStack Query
- Zod

## Backend
- Python 3.12+
- FastAPI
- Pydantic v2
- SQLAlchemy 2
- Alembic

## Database
- PostgreSQL 16+
- pgvector

## Cache
- Redis

## Workflow
- Temporal

## Browser
- Playwright

## Crawling
- httpx
- BeautifulSoup/lxml
- Playwright fallback

## Object Storage
- S3-compatible abstraction

## Development
- Docker
- pnpm
- uv

---

# 3. Repository Structure

```text
seo-engine/
├── apps/
│   ├── web/
│   ├── api/
│   └── worker/
├── packages/
│   ├── agent-runtime/
│   ├── agent-registry/
│   ├── orchestration/
│   ├── workflows/
│   ├── policies/
│   ├── permissions/
│   ├── memory/
│   ├── knowledge/
│   ├── evidence/
│   ├── events/
│   ├── integrations/
│   ├── prompts/
│   ├── schemas/
│   ├── observability/
│   └── shared/
├── agents/
│   ├── orchestrator/
│   ├── brand/
│   ├── research/
│   ├── seo/
│   ├── content/
│   ├── competitor/
│   ├── analytics/
│   ├── growth/
│   ├── local/
│   ├── ai-search/
│   ├── execution/
│   └── guardians/
├── integrations/
│   ├── google-search-console/
│   ├── google-analytics/
│   ├── google-ads/
│   ├── google-business-profile/
│   ├── ahrefs/
│   ├── semrush/
│   ├── wordpress/
│   ├── webflow/
│   └── generic-cms/
├── database/
│   ├── migrations/
│   ├── seeds/
│   └── schemas/
├── prompts/
├── tests/
├── docs/
├── infra/
├── docker-compose.yml
├── pnpm-workspace.yaml
├── pyproject.toml
├── README.md
└── .env.example
```

---

# 4. Core Domain

```text
Tenant
  ↓
User
  ↓
Brand
  ↓
Website
  ↓
Project
  ↓
Mission
  ↓
Task
  ↓
Agent
  ↓
Action
  ↓
Outcome
```

Every tenant-owned entity must include:

```text
tenant_id UUID NOT NULL
```

---

# 5. Minimum Database Schemas

## Identity
- tenants
- users
- tenant_users
- roles

## Brands
- brands
- brand_goals
- brand_services
- brand_products
- brand_audiences
- brand_locations
- brand_claims
- brand_voice_profiles
- brand_competitors

## Websites
- websites
- crawl_jobs
- crawl_pages
- pages
- page_links
- page_images
- page_schema
- page_issues

## Search
- keywords
- keyword_variants
- keyword_clusters
- keyword_metrics
- keyword_rankings
- serp_snapshots
- serp_results
- search_intents
- search_questions

## Content
- content_assets
- content_versions
- content_briefs
- content_research
- content_sources
- content_evaluations
- content_representation
- content_repairs

## Missions & Agents
- projects
- missions
- mission_tasks
- mission_metrics
- mission_progress
- agents
- agent_capabilities
- agent_tools
- agent_runs
- agent_outputs
- agent_messages
- tasks
- task_dependencies

## Memory & Evidence
- memories
- embeddings
- evidence
- evidence_relationships

## Strategy
- opportunities
- recommendations
- actions
- action_approvals
- outcomes
- experiments

## Platform
- policies
- events
- audit_logs
- integration_credentials
- llm_usage
- usage_events
- subscription_plans
- entitlements

---

# 6. Crawler Specification

The crawler must discover and store:

- robots.txt
- sitemap.xml
- sitemap indexes
- canonical URLs
- internal links
- external links
- redirect chains
- HTTP status
- title
- meta description
- H1-H6
- visible content
- word count
- structured data
- images
- alt text
- hreflang
- noindex
- nofollow
- content hash

Safeguards:
- max_pages
- max_depth
- rate_limit
- allowed_domains
- request_timeout
- concurrency
- robots policy
- redirect limit
- SSRF protection

Crawled content must be classified as:

```text
UNTRUSTED_EXTERNAL_CONTENT
```

---

# 7. Technical SEO Engine

Use deterministic code for deterministic checks.

Checks should include:

- blocked URLs
- non-200 responses
- 4xx
- 5xx
- redirect chains
- redirect loops
- missing title
- duplicate title
- boilerplate title
- keyword-stuffed title patterns
- missing meta description
- duplicate meta description
- missing H1
- competing H1s
- missing canonical
- canonical conflict
- noindex
- robots conflicts
- missing sitemap
- invalid sitemap URLs
- orphan pages
- broken internal links
- crawl-depth issues
- thin content
- duplicate content signals
- missing alt attributes
- structured data parse issues
- hreflang issues
- HTTP/HTTPS inconsistency

LLMs may interpret results, not replace deterministic validation.

---

# 8. Keyword Engine

Inputs:
- brand
- industry
- services
- products
- locations
- seed keywords
- competitors
- GSC queries
- third-party provider data

Pipeline:

```text
Seeds
 ↓
Expansion
 ↓
Normalisation
 ↓
Deduplication
 ↓
Intent Classification
 ↓
Clustering
 ↓
Scoring
 ↓
URL Mapping
 ↓
Gap Detection
```

Internal opportunity weighting:

```text
business_relevance      30%
intent_value            20%
demand                  15%
ranking_feasibility     15%
competitive_gap         10%
conversion_potential    10%
```

This is an internal prioritisation heuristic, not a Google ranking formula.

---

# 9. Search Intent

Supported classes:
- informational
- commercial
- transactional
- navigational
- local
- investigational

Allow probabilistic multi-intent representation.

---

# 10. Competitor Engine

Distinguish:
- business competitor
- SERP competitor
- content competitor
- local competitor
- paid competitor

Analyse:
- organic visibility
- ranking keywords
- top pages
- content clusters
- content freshness
- backlinks
- referring domains
- paid search presence
- local presence
- content gaps
- keyword gaps
- SERP ownership

---

# 11. Content Gap Engine

For each topic assess:
- business relevance
- search demand
- current rankings
- existing brand content
- competitor coverage
- SERP format
- authority fit
- conversion potential
- originality potential

Output exactly one action:

```text
CREATE
UPDATE
CONSOLIDATE
REDIRECT
DO_NOTHING
```

---

# 12. Content System

Content workflows:
- blog post
- pillar page
- service page
- product page
- landing page
- FAQ
- comparison page
- case study
- report
- ebook
- local page

Every content asset requires a brief before generation.

Brief fields:
- objective
- audience
- search intent
- primary topic
- secondary topics
- questions
- entities
- competitor pages
- missing information
- unique angle
- evidence
- expert input
- structure
- internal links
- external references
- CTA
- metadata

Quality gate:
- factual accuracy
- originality
- helpfulness
- reliability
- experience
- expertise
- authority
- trust
- search intent
- completeness
- readability
- brand alignment
- conversion relevance
- spam risk
- duplication
- unsupported claims

---

# 13. Agent Runtime

Implement:

- AgentRegistry
- AgentRunner
- AgentContextBuilder
- ToolResolver
- MemoryResolver
- PolicyResolver
- PermissionResolver
- EvidenceCollector
- ResultValidator

Canonical lifecycle:

```text
Task
 ↓
Load Agent
 ↓
Validate Capabilities
 ↓
Build Context
 ↓
Resolve Permissions
 ↓
Resolve Memory
 ↓
Resolve Tools
 ↓
Resolve Policy
 ↓
Execute
 ↓
Validate Result
 ↓
Persist
 ↓
Emit Event
```

---

# 14. Mission Engine

Mission fields:
- objective
- target_metric
- baseline
- target
- deadline
- automation_policy
- status

Example:

```json
{
  "objective": "Increase qualified organic leads",
  "target_metric": "organic_conversions",
  "baseline": 100,
  "target": 130,
  "deadline": "2027-02-01",
  "automation_policy": "assisted"
}
```

---

# 15. Workflow Engine

Use Temporal.

Initial workflows:
- BrandOnboardingWorkflow
- WebsiteAuditWorkflow
- KeywordResearchWorkflow
- CompetitorAnalysisWorkflow
- ContentProductionWorkflow
- ContentUpdateWorkflow
- SEORecommendationWorkflow
- AnalyticsSyncWorkflow
- AutonomousMonitoringWorkflow

---

# 16. Event Model

Core events:
- BrandCreated
- BrandUpdated
- WebsiteConnected
- WebsiteCrawled
- CrawlCompleted
- KeywordResearchStarted
- KeywordResearchCompleted
- CompetitorDiscovered
- AuditStarted
- AuditCompleted
- OpportunityDiscovered
- RecommendationCreated
- RecommendationApproved
- RecommendationRejected
- ContentBriefCreated
- ContentDraftCreated
- ContentReviewed
- ContentApproved
- ContentPublished
- TechnicalIssueDetected
- TechnicalIssueResolved
- AnalyticsSynced
- PerformanceChanged
- AnomalyDetected
- CampaignProposed
- CampaignApproved
- CampaignLaunched
- ExperimentStarted
- ExperimentCompleted
- OutcomeRecorded
- LearningCreated

---

# 17. Integration Architecture

Provider abstraction:

```python
class ProviderAdapter(Protocol):
    async def connect(self): ...
    async def health_check(self): ...
    async def capabilities(self): ...
    async def disconnect(self): ...
```

Initial providers:
- Google Search Console
- Google Analytics 4

Interfaces from day one:
- Ahrefs
- Semrush
- Google Ads
- Google Business Profile
- WordPress
- Webflow
- Generic CMS

Never fake production integrations.

---

# 18. Search Console Integration

Implement:
- OAuth
- property discovery
- search performance
- page/query dimensions
- country
- device
- search appearance where available
- sitemaps
- URL inspection

Store raw provider data separately from normalised records.

---

# 19. GA4 Integration

Implement:
- OAuth
- property discovery
- users
- sessions
- landing pages
- engagement
- events
- conversions
- revenue where available
- acquisition dimensions

Store raw provider data separately from normalised records.

---

# 20. Action Lifecycle

```text
PROPOSED
 ↓
PENDING_APPROVAL
 ↓
APPROVED
 ↓
EXECUTING
 ↓
EXECUTED
```

Failure path:

```text
EXECUTING
 ↓
FAILED
 ↓
RETRY / BLOCKED / ROLLED_BACK
```

Every action records:
- actor
- timestamp
- before state
- after state
- reason
- evidence
- approval
- provider
- external ID
- rollback metadata

---

# 21. Security

Mandatory:
- authentication
- RBAC
- tenant isolation
- encrypted secrets
- OAuth token protection
- capability enforcement
- audit logs
- API validation
- rate limiting
- secure headers
- SSRF protection
- prompt-injection defence
- webhook verification
- action idempotency

External content categories:

```text
SYSTEM
APPLICATION_POLICY
USER_INPUT
TOOL_OUTPUT
UNTRUSTED_EXTERNAL_CONTENT
```

External website content must never become instructions.

---

# 22. API Baseline

Base path:

```text
/api/v1
```

Core endpoints:

```text
POST /auth/register
POST /auth/login

GET /brands
POST /brands
GET /brands/{id}
PATCH /brands/{id}

POST /brands/{id}/websites
GET /websites/{id}
POST /websites/{id}/crawl
GET /websites/{id}/pages
GET /websites/{id}/issues

POST /brands/{id}/keyword-research
GET /brands/{id}/keywords
GET /brands/{id}/keyword-clusters

POST /brands/{id}/competitor-analysis
GET /brands/{id}/competitors

GET /brands/{id}/opportunities
GET /brands/{id}/recommendations

POST /brands/{id}/missions
GET /missions/{id}
POST /missions/{id}/run
GET /missions/{id}/tasks
GET /missions/{id}/events

POST /recommendations/{id}/approve
POST /recommendations/{id}/reject

POST /actions/{id}/execute

POST /content/briefs
POST /content/generate
POST /content/update
POST /content/evaluate
POST /content/repurpose

POST /integrations/gsc/connect
POST /integrations/ga4/connect

GET /analytics/gsc
GET /analytics/ga4
```

---

# 23. Frontend

Primary navigation:
- Dashboard
- Brands
- Brand Brain
- Website
- Technical SEO
- Keywords
- Competitors
- Content
- Opportunities
- Recommendations
- Missions
- Analytics
- Integrations
- Activity
- Settings

Recommendation screen should show:
- what
- why
- evidence
- expected impact
- effort
- risk
- confidence
- affected pages
- recommended action
- approval state

---

# 24. Observability

Track:
- request IDs
- correlation IDs
- workflow IDs
- task IDs
- agent run IDs
- agent latency
- model/provider
- LLM usage/cost
- crawl pages
- crawl errors
- workflow duration
- workflow failures
- recommendations created
- recommendations approved
- actions executed
- actions failed

---

# 25. Testing

Required:
- unit tests
- integration tests
- API tests
- crawler tests
- parser tests
- agent tests
- workflow tests
- permission tests
- tenant isolation tests
- provider mock tests
- regression tests
- prompt-injection tests
- SSRF tests
- high-risk approval tests

Golden evaluation datasets:
- keyword_research.json
- competitor_analysis.json
- technical_audit.json
- content_brief.json
- content_quality.json
- recommendations.json

---

# 26. Definition of MVP Done

The MVP is complete only when a user can:

1. Create an organisation.
2. Add a brand.
3. Define business context.
4. Add a website.
5. Crawl it.
6. Receive a technical audit.
7. Connect GSC.
8. Connect GA4.
9. Retrieve search/analytics data.
10. Research keywords.
11. Analyse competitors.
12. Detect gaps.
13. Generate opportunities.
14. Prioritise recommendations.
15. Create a content brief.
16. Generate/update content.
17. Review and approve content.
18. Execute an approved action through a supported connector.
19. Measure the outcome.
20. See the result stored against the action and mission.

The canonical acceptance mission is:

> **Increase qualified organic leads.**
