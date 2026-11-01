# BRD-003 — Business Objective Agent

## Purpose

Maps each stated goal to the metric that would measure it (declared goal type first, then wording) and the data source that metric needs, then checks the source is connected and — for lead goals — that an analytics event is identified as a lead. A goal that cannot be measured is reported with its blockers and the fix; no target or baseline is ever set or estimated.

## Inputs

Schema: `BusinessObjectiveInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id` | UUID | The brand whose goals are assessed. |
| `website_id` | UUID \| None | Needed for index-coverage goals. |

## Outputs

Schema: `BusinessObjectiveOutput`.

| Field | Meaning |
| --- | --- |
| `assessments` | Per goal: metric, data source, measurable, blockers, specificity gaps. |
| `connected_providers / lead_events` | What was actually available. |

## Capabilities

- `brand.objectives.assess`

## Tools

- `memory`

## Memory

- **Scopes:** `brand`
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
| No goals recorded | Recommends recording one; assesses nothing. |
| Provider not connected | The goal is unmeasurable, with that blocker and its fix. |
| No lead event identified | A lead goal is unmeasurable until one is confirmed. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. reports goals unmeasurable when their provider is absent;
2. lets the declared goal type outrank a word in the description;
3. recommends a fix for each blocker, citing the goal and the connection state.
