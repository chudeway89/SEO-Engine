# Agents

An agent in SEO Engine is not a prompt. It is a declared, sandboxed unit of work
with explicit capabilities, tools, memory scopes, permissions, a risk level and
approval requirements (Rule 4), and it runs through exactly one path: the Agent
Runtime.

## Anatomy of an agent

Every agent is a directory under `agents/`:

```
agents/<domain>/<name>/
├── manifest.yaml   # the contract: id, capabilities, tools, memory scopes, risk, approvals
├── agent.py        # the implementation: a BaseAgent subclass, exported as AGENT
├── schemas.py      # the typed input and output models
├── prompt.md       # the narration prompt (only used in hybrid mode; never produces decisions)
└── README.md       # purpose, inputs, outputs, failure modes, evaluation criteria (§79)
```

`agent.py` loads its sibling `schemas.py` with
`seo_engine.agent_runtime.loader.load_agent_module(__file__)`, which registers the
module before executing it so Pydantic can resolve its annotations. (The first
eleven agents predate that loader and keep their contracts inline in
`agent.py`.) Agent directory names must be unique across domains: the loader
keys the schema module by directory name.

Behavioural tests live under `tests/agent/` rather than inside each agent
directory, because pytest collects from `tests/` and same-named test modules in
sibling directories would collide. `tests/fixtures/agents.py` provides a harness
that runs any agent through the real runtime against the in-process demo site.
`tests/unit/test_agent_catalogue.py` checks the catalogue as data: every agent
directory is complete, every stage's agent declares the stage's capabilities,
every mission lists stages after their dependencies, and every agent but the
planner has a place in some mission.

The registry loads every `manifest.yaml`, validates it against the
`AgentManifest` schema, and instantiates the `AGENT` class. An invalid manifest
is rejected at load time — for example, a memory *type* mistakenly listed as a
memory *scope* fails fast rather than silently mis-resolving at run time.

## The lifecycle

The runner (`seo_engine.agent_runtime.runner`) is the only way an agent runs:

```
load agent → validate capabilities → build context →
resolve permissions → resolve memory → resolve tools → execute →
validate result → persist → emit event
```

Every step is mandatory. A failure at any step fails the run, records why, and
emits an event. Nothing is silently skipped and no partial result is treated as
success.

- **Capabilities** — the manifest must declare at least one; an agent with none
  cannot run.
- **Permissions** — resolved as the intersection of the manifest and the calling
  principal. An agent never gains a permission its operator lacks.
- **Memory** — only the declared scopes are visible. The resolver refuses any
  access outside them.
- **Tools** — only the declared tools, and each is marked unavailable (rather
  than silently working) when its integration is not connected or the operator
  lacks the permission. The two gates are distinct: "you may not" and "it is not
  connected" are different answers.
- **Services** — agents receive domain services, never a database handle
  (Rule 4). Every service is built with the principal, so an agent's data access
  carries the same tenant and permission checks a user's would.

## The result validator

`ResultValidator` runs on every result and was written before any agent, so none
can bypass it. It enforces:

- **Evidence or hypothesis (Rule 7):** a recommendation cites evidence that
  actually exists, or is explicitly flagged a hypothesis with capped confidence.
- **No chain-of-thought (Rule 8):** user-facing fields are scanned for leaked
  deliberation; a match fails the result. The platform exposes observations,
  evidence, conclusions, recommendations, confidence and limitations — never
  private reasoning.
- **Declared actions only:** an agent may propose only the action types its
  manifest lists. An empty declaration denies everything.
- **Approval for risk:** a high-risk recommendation or action that does not set
  `requires_approval` fails.
- **The approval floor:** an action type the manifest lists under
  `approval_required_for` waits for a person *whatever policy allows*. The floor
  is enforced where the action is created (`DecisionService.propose_action(...,
  approval_floor=...)`), so the stricter of policy and manifest always wins.
- **No fabricated metrics (Rule 14):** evidence provenance is checked;
  near-certain confidence on an inference is rejected.

## Synthesis modes and models

SEO Engine is **model-agnostic** and **model-optional**.

* **No model is required.** Every agent is `deterministic` at its core: its
  structured output — figures, findings, decisions, actions — comes from the
  deterministic engines. The `ModelGateway`'s default provider raises
  `DeterministicFallbackRequired` rather than inventing prose, so a model-less
  deployment runs every agent and every mission. Each manifest's
  `model_policy.deterministic_fallback` must be `true`; a manifest that says
  otherwise is rejected at load.
* **Any model can be connected.** A provider speaks a protocol, not a model:
  `openai_compatible` (any Chat Completions endpoint, hosted or local, keyless
  servers included), `anthropic` (any model on the Messages API), or anything
  registered with `seo_engine.shared.llm.register_provider`. The operator names
  the model (`LLM_MODEL`); there is no default model, and no agent can pin one —
  manifests carry no model, temperature or reasoning settings. Sampling is sent
  only if the operator sets it, and a parameter a model rejects is dropped and
  the request repeated.
* **A model never decides anything.** Only the content writer (CNT-004) calls a
  model, and only to write prose inside a brief it did not author. A run whose
  drafts a model wrote reports `synthesis_mode: hybrid`.
* **A failing model never stops the platform.** Transient failures are retried;
  a model that is unreachable, misconfigured, returns nothing usable, or is cut
  off at the output limit is handled like no model (or flagged, for a cut-off
  draft), and the run's limitations say why. Reasoning blocks some models emit
  inline (`<think>…</think>`) are stripped before anything sees the text.
* **Every call is attributable.** The runtime gives each run its own gateway
  view and records every model call in `llm_usage` against the run: provider,
  model, tokens and stop reason as reported, and cost from operator-configured
  prices — `NULL`, never zero, when unknown. `GET /readyz` reports which model,
  if any, is in use and why a configured one is not usable.

Tests inject a gateway through `services["model_gateway"]` with a scripted
provider that stands in for any model (`tests/fixtures/models.py`); both
protocol providers are tested against in-process fakes of their APIs.

## The MVP agents

All 36 agents named by the build prompt are implemented. Each is deterministic
at its core and runs without a model; only the content writer can use one, and
only to write prose inside a brief it did not author.

| ID | Agent | Risk | Deterministic core |
| --- | --- | --- | --- |
| ORCH-001 | Brand and Strategy Orchestrator | low | objective → selected, dependency-ordered stages, with reasons for every exclusion |
| BRD-001 | Brand Understanding | low | the brand graph → working model + completeness |
| BRD-002 | Brand Profile | low | profile vs crawled site → proposals (never writes the brand graph) |
| BRD-003 | Business Objective | low | goal → measurable metric, data source and blockers |
| RES-001 | Search Research | low | Search Console rows → demand landscape with provenance |
| RES-002 | SERP Research | low | SERP integration → stored snapshots, features, recurring domains |
| RES-005 | Question Research | low | questions from three sources, weakest provenance, answering page |
| RES-006 | Source and Evidence | low | source register: tiered by rule, verified only by fetch |
| SEO-001 | Technical SEO | low | crawl + nine-dimension deterministic checks |
| SEO-002 | On-Page SEO | low | mapped keyword vs title/H1/meta/copy/URL alignment |
| SEO-003 | Keyword Intelligence | low | keyword pipeline, clustering, intent |
| SEO-004 | Search Intent | low | query intent (SERP-refined) vs page type |
| SEO-005 | Keyword Cluster | low | cannibalisation and hub-and-spoke linking |
| SEO-006 | Content Gap | low | CREATE/UPDATE/CONSOLIDATE/REDIRECT/DO_NOTHING per topic |
| SEO-012 | Indexability | low | sitemap × crawl × priority pages × Search Console reconciliation |
| CMP-001 | Competitor Discovery | low | recurring SERP domains vs recorded competitors (synthetic never proposed) |
| CMP-002 | Competitor Analysis | low | competitor crawl + coverage comparison |
| CMP-003 | Competitive Gap | low | coverage × visibility, transparently scored |
| ANA-001 | Search Console Analytics | low | measured performance + recoverable queries |
| ANA-002 | GA4 Analytics | low | organic qualified-lead baseline |
| OPP-001 | Opportunity Detection | low | observations and upstream seeds → evidence-backed opportunities |
| PRI-001 | Opportunity Prioritisation | low | impact × confidence × fit ÷ effort |
| DEC-001 | Decision | medium | the pre-recommendation review gate |
| CNT-001 | Content Strategist | low | gap decisions → capacity-bounded roadmap, fixes before new pages |
| CNT-002 | Content Research | low | research pack from held evidence only |
| CNT-003 | Content Brief | low | the definitive brief, with approved and prohibited claims |
| CNT-004 | Content Writer | medium | brief → draft; with no model, a labelled outline, never invented prose |
| CNT-005 | Content Optimisation | low | weak criteria → tracked, specific edits |
| CNT-006 | Content Update | medium | live page vs its brief → update plan (approval-gated) |
| CNT-007 | Content Evaluator | low | twelve criteria, four blocking, recorded per version |
| CNT-008 | Content Repurposing | low | reviewed canonical → platform derivatives naming their source |
| CNT-009 | Content Quality Guardian | medium | the gate to human review: outline, duplicate, thin, scaled |
| QUAL-001 | Quality Guardian | low | recommendations vs the evidence store |
| POL-001 | Policy Guardian | medium | brand content rules + policy drift on open actions |
| EXE-001 | Execution | medium | approved recommendations → policy-gated actions |
| PUB-001 | Publishing | high | publishes only what every gate and approval allows |

Each agent's own `README.md` documents its inputs, outputs, failure modes and
evaluation criteria. The orchestrator selects which of these a given mission
actually needs — a lead mission runs the full analysis chain; a competitor-focused
objective does not run the GA4 baseline; a content-production objective runs the
content pipeline through publishing — and records why each omitted stage was
omitted rather than running everything every time (Rule 15: no shallow agents
run for the sake of coverage).

### How the stages connect

* **Hard and ordering dependencies.** A stage's `depends_on` are prerequisites:
  if one is excluded, so is the stage. Its `after` only orders it: search intent
  runs after SERP research when SERP research is in the plan, and without it
  when it is not, reporting the missing input as a limitation.
* **Opportunity seeds.** Analysis agents (on-page, indexability, search intent,
  keyword architecture, question research, competitive gap) do not write
  opportunities. They emit evidenced seeds (`engines.opportunities.detection.seed`)
  in their output; opportunity detection persists and prioritises them, and
  refuses any seed that cites no evidence.
* **Approval stays human.** The content service handed to agents is built with
  `acting_as_agent=True` and refuses to approve content. The quality gate can move
  a draft to review; a person approves it (`POST /content/{id}/approve`); the
  publishing agent then proposes `cms.publish`, which the policy engine gates and a
  person approves again where policy requires.
* **A person can write what a model could not.** Without a model the writer
  leaves an outline. A person writes the piece (`POST /content/{id}/versions`, or
  the content screen in the web app), and `POST /content/{id}/review` runs
  CNT-007, CNT-009 and POL-001 against that exact version through the runtime.
  A version is labelled with who wrote it: `llm`, `deterministic` (an outline)
  or `human`.
* **Approved SEO changes are applied, not guessed.** Seeds carry a concrete
  change specification (`data["change"]`: the exact new title, the link to add)
  through opportunity → recommendation → action. EXE-001 applies an approved
  `seo.metadata_update` (page title) or `seo.internal_link_add` through the
  brand's connected CMS (`integrations.cms.changes`). An approved action without
  a concrete change, or of a kind with no safe general executor (structured
  data, redirects), is reported and left approved for a person — never invented,
  never marked failed. A draft action needs the written draft; an empty CMS
  draft is never created.

## Golden evaluation datasets

`tests/evaluation/golden/*.json` holds data-driven cases (a brand fixture, the
agent's inputs, and expectations on its output, findings, recommendations and
limitations) that `tests/evaluation/test_golden.py` runs through the real
runtime. They currently cover BRD-001, BRD-003, ORCH-001, CNT-001 and CMP-003;
every other agent's behaviour is asserted in `tests/agent/`. Add a case by adding
JSON — no code.

## Writing a new agent

1. Create the directory and a `manifest.yaml` declaring the contract.
2. Define `schemas.py` with the input and output models.
3. Implement `agent.py` as a `BaseAgent` subclass exported as `AGENT`; do the
   real work in the deterministic engines and call them from the agent.
4. Write `prompt.md` only if the agent has a narration mode.
5. Write `README.md` to the §79 structure (or add the agent to
   `database/gen_agent_docs_extended.py`) and behavioural tests under
   `tests/agent/`.
6. Add the stage to the orchestrator's `STAGE_SPECS` and to every mission that
   needs it, and give it inputs in `workflows/steps.py`. The catalogue test fails
   until the agent has a place in some mission.

The runtime enforces the rest: an agent cannot reach the database, exceed its
declared scopes, propose an undeclared action, or return a result that fails the
validator.
