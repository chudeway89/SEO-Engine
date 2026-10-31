# PRI-001 — Opportunity Prioritisation Agent

## Purpose

Ranks detected opportunities by the internal prioritisation model — impact × confidence × strategic fit ÷ effort, normalised. The formula is explicit and is not a Google ranking factor; it is how the platform sequences its own work, and it is applied deterministically so the ordering is reproducible and explainable.

## Inputs

Schema: `PrioritisationInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id` | UUID | The brand. |
| `mission_id` | UUID \| None | The mission whose opportunities are ranked. |
| `limit` | int | Upper bound on opportunities scored (default 50). |

## Outputs

Schema: `PrioritisationOutput`.

| Field | Meaning |
| --- | --- |
| `prioritised` | Opportunities in ranked order, each with its score breakdown. |
| `score_breakdown` | The contribution of impact, confidence, strategic fit and effort to each score. |

## Capabilities

- `opportunity.prioritise`

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

None required. `approval_required_for` is empty, so the result validator rejects any action this agent attempts to propose.

## Failure modes

| Mode | Behaviour |
| --- | --- |
| No opportunities to rank | Returns a limitation and an empty ranking. |
| An opportunity has non-positive effort | Rejected upstream by the validator; prioritisation never divides by zero. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. orders opportunities by the stated formula, reproducibly;
2. exposes the score breakdown so a ranking can be explained, not just asserted;
3. never presents the internal score as a search ranking or a Google signal;
4. returns an empty, explained result when there is nothing to rank.
