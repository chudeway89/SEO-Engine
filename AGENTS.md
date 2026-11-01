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
├── README.md       # purpose, inputs, outputs, failure modes, evaluation criteria (§79)
└── tests/          # behavioural tests
```

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
- **No fabricated metrics (Rule 14):** evidence provenance is checked;
  near-certain confidence on an inference is rejected.

## Synthesis modes

Most MVP agents are `deterministic`: their structured output comes entirely from
the deterministic engines, with no model call. A `hybrid` agent may additionally
produce a narrative summary from a model — but the model only narrates what the
deterministic path already decided. It never produces a figure, a decision or an
action. The `ModelGateway`'s deterministic provider raises
`DeterministicFallbackRequired` rather than inventing prose, so a model-less
deployment still runs every agent and simply omits the narration.

## The MVP agents

| ID | Agent | Risk | Deterministic core |
| --- | --- | --- | --- |
| BRD-001 | Brand Understanding | low | the brand graph → working model + completeness |
| SEO-001 | Technical SEO | low | crawl + nine-dimension deterministic checks |
| SEO-003 | Keyword Intelligence | low | keyword pipeline, clustering, intent |
| SEO-006 | Content Gap | low | CREATE/UPDATE/CONSOLIDATE/REDIRECT/DO_NOTHING per topic |
| CMP-002 | Competitor Analysis | low | competitor crawl + coverage comparison |
| ANA-001 | Search Console Analytics | low | measured performance + recoverable queries |
| ANA-002 | GA4 Analytics | low | organic qualified-lead baseline |
| OPP-001 | Opportunity Detection | low | observations → evidence-backed opportunities |
| PRI-001 | Opportunity Prioritisation | low | impact × confidence × fit ÷ effort |
| DEC-001 | Decision | medium | the pre-recommendation review gate |
| EXE-001 | Execution | medium | approved recommendations → policy-gated actions |

Each agent's own `README.md` documents its inputs, outputs, failure modes and
evaluation criteria. The orchestrator selects which of these a given mission
actually needs — a lead mission runs the full chain; a competitor-focused
objective does not run the GA4 baseline — and records why each omitted stage was
omitted rather than running everything every time (Rule 15: no shallow agents
run for the sake of coverage).

## Writing a new agent

1. Create the directory and a `manifest.yaml` declaring the contract.
2. Define `schemas.py` with the input and output models.
3. Implement `agent.py` as a `BaseAgent` subclass exported as `AGENT`; do the
   real work in the deterministic engines and call them from the agent.
4. Write `prompt.md` only if the agent has a narration mode.
5. Write `README.md` to the §79 structure and behavioural tests under `tests/`.
6. Add the stage to the orchestrator if it belongs in a mission graph.

The runtime enforces the rest: an agent cannot reach the database, exceed its
declared scopes, propose an undeclared action, or return a result that fails the
validator.
