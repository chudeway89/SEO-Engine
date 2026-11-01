# ORCH-001 — Brand and Strategy Orchestrator

## Purpose

The orchestrator as an auditable agent run. Given an objective (or the brand's top goal) it classifies the mission, selects the stages that mission needs using the same `Orchestrator` the mission workflow uses, records why every other stage is not run, and recommends what the brand would need to connect to unlock them. It delegates through `next_tasks` and never executes a tool or performs another agent's work (Build Specification §29). Exposed as `POST /brands/{id}/strategy`, a preview that creates no mission.

## Inputs

Schema: `StrategyInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id` | UUID | The brand to plan for. |
| `objective` | str \| None | Plain-language objective; the top recorded goal when omitted. |
| `website_id` | UUID \| None | Counts as a connected website when supplied. |

## Outputs

Schema: `StrategyOutput`.

| Field | Meaning |
| --- | --- |
| `mission_type / target_metric` | The classification and its measurable metric (or none). |
| `stages` | Selected stages with agent, dependencies and the selection reason. |
| `excluded` | Every stage not run, with the reason. |
| `readiness` | Website, connected providers, competitors and goals actually recorded. |

## Capabilities

- `orchestration.plan`

## Tools

- `memory`

## Memory

- **Scopes:** `brand`, `mission`
- Writes are confined to those scopes; the runtime refuses any memory access a
  scope here does not grant.

## Permissions

Resolved as the intersection of this manifest and the calling principal. The
agent runs through the Agent Runtime and reaches data only through tenant-scoped
domain services — never the database directly (Rule 4).

## Risk

`low`.

## Approval

None required. `approval_required_for` is empty, so the result validator rejects any action this agent attempts to propose. Its outputs are findings, evidenced opportunity seeds or recommendations; nothing it produces changes the live site.

## Failure modes

| Mode | Behaviour |
| --- | --- |
| No objective and no goals | Returns a limitation and no plan; nothing is guessed. |
| A provider is not connected | The dependent stages are excluded with that reason and an `integration.connect` recommendation is made. |
| Mission type has no single metric | Says progress is reported per stage, not against an invented number. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. produces next tasks for every selected stage and no actions or tool use;
2. excludes provider-dependent stages with a reason when nothing is connected;
3. recommends connecting each missing provider, citing the readiness observation;
4. returns the same selection the mission workflow would make.
