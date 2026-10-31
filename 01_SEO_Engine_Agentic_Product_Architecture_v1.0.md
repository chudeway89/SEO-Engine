# SEO Engine — Agentic Product Architecture v1.0

## 1. Product Definition

SEO Engine is an agentic SEO and digital growth operating system that continuously:

**Understands → Researches → Diagnoses → Strategises → Prioritises → Creates → Optimises → Executes → Measures → Learns → Repeats**

It is not a chatbot with SEO prompts. The conversational interface is only one interface into the underlying operating system.

The platform is designed to understand a brand, analyse its market and website, research search demand and competitors, identify opportunities, develop strategies, create and optimise content, execute approved actions, measure outcomes, and retain institutional memory.

---

## 2. Core Product Thesis

> SEO Engine is a persistent, evidence-based, policy-controlled, multi-agent operating system that manages a brand's search and digital growth objectives over time.

The product should evolve from:

> “Here is your SEO report.”

to:

> “I found 47 opportunities. I prioritised 12. Three are high-confidence, high-impact and low-risk. I prepared the changes. Approve the actions you want executed.”

and eventually:

> “Your approved automation policy allows low-risk technical fixes and metadata changes. I executed six qualifying actions, logged everything, and am monitoring the results.”

---

## 3. Canonical Operating Loop

```text
OBSERVE
   ↓
UNDERSTAND
   ↓
RESEARCH
   ↓
DIAGNOSE
   ↓
STRATEGISE
   ↓
PRIORITISE
   ↓
CREATE
   ↓
OPTIMISE
   ↓
APPROVE
   ↓
EXECUTE
   ↓
MEASURE
   ↓
LEARN
   ↓
OBSERVE
```

---

## 4. Architectural Principles

1. **Agent-first architecture**  
   Capabilities belong to specialised agents operating through a shared runtime.

2. **Evidence before recommendation**  
   Consequential recommendations must be supported by evidence.

3. **Recommendation before execution**  
   Strategy agents do not directly execute consequential actions.

4. **Capability-based permissions**  
   Every agent has declared tools, capabilities, memory scopes, permissions and risk limits.

5. **Policy-driven human control**  
   The user defines what the system may do automatically, what requires approval, and what is forbidden.

6. **Full auditability**  
   Every consequential decision and action records who, what, when, why, evidence, policy, tool and result.

7. **Existing assets before new assets**  
   Before creating a page, evaluate whether an existing page should be improved, consolidated, redirected or left unchanged.

8. **Content must have a reason to exist**  
   A keyword alone does not justify a new page.

9. **No invented expertise or evidence**  
   Never fabricate credentials, experience, research, claims, citations, testimonials, case studies or statistics.

10. **People-first optimisation**  
    Optimise for users first, with search engines and AI systems as discovery mechanisms.

11. **No ranking guarantees**  
    SEO Engine produces evidence, confidence and opportunity estimates, not guarantees.

12. **Third-party data is evidence, not truth**  
    Ahrefs, Semrush and other tools provide useful estimates, not Google's proprietary ranking data.

13. **AI Search is an extension of Search**  
    The system should not rely on unverified “GEO hacks”.

14. **Agentic web readiness is separate from SEO**  
    Future auditing should include machine-interaction readiness for browser agents.

---

## 5. High-Level Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                        SEO ENGINE                           │
├─────────────────────────────────────────────────────────────┤
│ EXPERIENCE                                                  │
│ Web App │ Command Centre │ Reports │ Content │ Approvals     │
├─────────────────────────────────────────────────────────────┤
│ API / BFF                                                   │
├─────────────────────────────────────────────────────────────┤
│ AGENT CONTROL PLANE                                         │
│ Orchestrator │ Registry │ Tasks │ Workflows │ Policies       │
│ Permissions │ Approvals │ Events │ Audit                    │
├─────────────────────────────────────────────────────────────┤
│ INTELLIGENCE PLANE                                          │
│ Research │ SEO │ Content │ Competitive │ Growth │ Analytics │
│ Local │ AI Search │ Decision │ Guardians                    │
├─────────────────────────────────────────────────────────────┤
│ EXECUTION PLANE                                             │
│ CMS │ Technical │ GSC │ GA4 │ GBP │ Ads                    │
├─────────────────────────────────────────────────────────────┤
│ MEMORY / KNOWLEDGE                                          │
│ Brand │ Working │ Historical │ Outcome │ Graph │ Evidence   │
├─────────────────────────────────────────────────────────────┤
│ TOOLS                                                       │
│ Browser │ Crawler │ Search │ GSC │ GA4 │ Ahrefs │ Semrush   │
│ Google Ads │ GBP │ CMS │ LLM Providers                     │
├─────────────────────────────────────────────────────────────┤
│ DATA                                                        │
│ PostgreSQL │ pgvector │ Redis │ Object Storage              │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. Control Planes

### 6.1 Experience Plane
User-facing interaction:
- Command Centre
- Brand Brain
- SEO Intelligence
- Search Intelligence
- Competitors
- Content
- Local SEO
- Paid Growth
- Analytics
- Missions
- Recommendations
- Approvals
- Automations
- Integrations
- Reports
- Settings

### 6.2 Agent Control Plane
Responsible for:
- task decomposition
- agent selection
- capability checks
- workflow orchestration
- memory retrieval
- policy evaluation
- permission enforcement
- approval handling
- event emission
- audit logging

### 6.3 Intelligence Plane
Responsible for:
- research
- analysis
- recommendations
- strategy
- content intelligence
- competitor intelligence
- decision quality

### 6.4 Execution Plane
Responsible for approved changes only:
- CMS
- technical SEO
- content publication
- internal links
- GSC
- GBP
- Google Ads

### 6.5 Observation & Learning Plane
Responsible for:
- performance collection
- anomalies
- outcomes
- experiments
- learning records
- mission progress

---

## 7. Mission-Centric Architecture

The core product object is a **Mission**, not an SEO audit.

Examples:

- Increase qualified organic leads.
- Recover lost organic traffic.
- Launch a new service.
- Improve local visibility.
- Build topical authority.
- Defeat competitor X for topic Y.
- Reduce paid acquisition cost.
- Prepare the site for AI-agent interaction.

### Mission Lifecycle

```text
CREATED
   ↓
PLANNING
   ↓
ACTIVE
   ↓
MONITORING
   ↓
ADAPTING
   ↓
ACHIEVED
```

Alternative terminal/intermediate states:

```text
PAUSED
FAILED
CANCELLED
EXPIRED
```

---

## 8. Memory Architecture

SEO Engine uses hybrid memory:

```text
Structured Memory    Semantic Memory    Graph Memory
PostgreSQL           pgvector           Knowledge relationships
```

### Memory Types

1. **Brand Memory**
   - products
   - services
   - audiences
   - locations
   - business model
   - tone
   - approved claims
   - experts
   - competitors
   - goals

2. **Working Memory**
   - current task findings
   - temporary hypotheses
   - active constraints

3. **Historical Memory**
   - prior audits
   - recommendations
   - actions
   - content
   - campaigns
   - experiments

4. **Outcome Memory**
   - action
   - baseline
   - result
   - time window
   - confidence
   - context

### Learning Principle

SEO Engine must learn conditionally.

Bad learning:

> “Changing titles improves rankings.”

Good learning:

> “For commercial service pages with existing impressions and weak CTR, title improvements correlated with higher CTR over a 28-day observation window.”

---

## 9. Knowledge Graph

Core entities:

- Brand
- Person
- Product
- Service
- Topic
- Keyword
- Query
- Page
- Competitor
- Location
- Organisation
- Claim
- Source
- Author
- Campaign
- Conversion
- Experiment
- Action
- Outcome

Example relationships:

```text
Brand ─offers→ Service
Service ─targets→ Audience
Service ─related_to→ Topic
Topic ─targets→ Keyword
Keyword ─mapped_to→ Page
Page ─competes_with→ Page
Person ─expert_in→ Topic
Source ─supports→ Claim
Action ─produced→ Outcome
```

---

## 10. Evidence Architecture

Every important recommendation should be traceable to evidence.

Evidence types:

- OBSERVATION
- DOCUMENT
- API_DATA
- CRAWL_RESULT
- SERP_RESULT
- EXPERIMENT
- HUMAN_INPUT
- MODEL_INFERENCE

The UI should distinguish:

- **Data**
- **Observation**
- **Inference**
- **Recommendation**

Inference must never be presented as fact.

---

## 11. Permissions and Risk

### Permission Levels

```text
READ
PROPOSE
EXECUTE
AUTONOMOUS
DENY
```

### Risk Levels

```text
LOW
MEDIUM
HIGH
CRITICAL
```

Examples:

**Low**
- generate draft
- analyse page
- create recommendation

**Medium**
- metadata update
- internal link change
- schema update

**High**
- redirect
- page deletion
- high-risk content publication
- campaign changes

**Critical**
- large budget changes
- bulk deletions
- migration
- security/access modifications

---

## 12. Policy-Driven Automation

The product should ask:

> “What am I allowed to do?”

not repeatedly:

> “Should I do this?”

Automation modes:

### Conservative
Everything requires approval.

### Assisted
Low-risk actions may be automated.

### Autonomous
Approved action categories may execute automatically within guardrails.

### Enterprise
Organisation-specific policies.

---

## 13. Agentic Content Pipeline

```text
Opportunity
   ↓
Content Gap
   ↓
Research
   ↓
Source Verification
   ↓
Brief
   ↓
Draft
   ↓
Edit
   ↓
Fact Check
   ↓
E-E-A-T Review
   ↓
Originality Review
   ↓
Risk Review
   ↓
Publishing Guardian
   ↓
Approval
   ↓
Publish
   ↓
Measure
   ↓
Learn
```

Before content creation, the system must decide:

```text
CREATE
UPDATE
CONSOLIDATE
REDIRECT
DO NOTHING
```

---

## 14. Search Intelligence Model

The keyword engine should not stop at:

> Keyword | Volume | Difficulty

Opportunity should consider:

```text
Search Demand
× Business Relevance
× Intent Strength
× Conversion Potential
× SERP Opportunity
× Authority Fit
× Competitive Gap
÷ Effort
```

The system must understand:
- user problem
- likely intent
- funnel stage
- content type
- existing asset suitability
- business value

---

## 15. Execution Model

```text
Recommendation
   ↓
Policy Evaluation
   ↓
Approval (if required)
   ↓
Action
   ↓
Executor Agent
   ↓
External System
   ↓
Result
   ↓
Outcome Measurement
   ↓
Learning
```

Execution agents do not create strategy.

---

## 16. Commercial Architecture

Design for multi-tenancy from day one:

```text
Organisation
 ├── Users
 ├── Brands
 ├── Websites
 ├── Locations
 ├── Competitors
 ├── Integrations
 ├── Content
 ├── Keywords
 ├── Projects
 ├── Missions
 ├── Recommendations
 ├── Actions
 ├── Reports
 └── Usage
```

Future plans may include:
- Starter
- Pro
- Growth
- Agency
- Enterprise

Entitlements should control:
- brands
- websites
- agent runs
- integrations
- crawl limits
- content generation
- automation
- analytics history
- paid-media controls

---

## 17. Technology Baseline

Frontend:
- Next.js
- TypeScript
- Tailwind CSS
- shadcn/ui
- TanStack Query

Backend:
- Python 3.12+
- FastAPI
- Pydantic v2
- SQLAlchemy 2
- Alembic

Data:
- PostgreSQL
- pgvector
- Redis
- S3-compatible object storage

Workflow:
- Temporal

Crawler:
- httpx
- BeautifulSoup/lxml
- Playwright fallback

Deployment:
- Docker
- Terraform later
- modular monolith first

---

## 18. Long-Term Product Position

SEO Engine should evolve beyond an “SEO tool”.

The long-term category is:

> **AI Growth Operating System**

The product moat is not the LLM.

It is:

```text
Brand graph
+
Search data
+
Historical observations
+
Recommendations
+
Actions
+
Outcomes
+
Experiments
+
Tenant-specific memory
+
Agent performance
```

The product should become increasingly good at answering:

> What works, for whom, under what conditions, and with what business outcome?
