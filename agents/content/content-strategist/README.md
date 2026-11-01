# CNT-001 — Content Strategist Agent

## Purpose

Sequences content gap decisions into a capacity-bounded roadmap: consolidate and update existing pages before creating new ones, order each phase by commercial intent, service alignment and gap confidence, schedule no more than the stated capacity per month, and report the backlog and the DO_NOTHING topics with their reasons.

## Inputs

Schema: `ContentStrategyInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id` | UUID | The brand. |
| `content_gaps` | list[dict] | Decisions from the content gap stage. |
| `months / capacity_per_month` | int | Plan length and capacity. |

## Outputs

Schema: `ContentStrategyOutput`.

| Field | Meaning |
| --- | --- |
| `roadmap` | Scheduled items by month, backlog, not-pursued topics, the priority formula. |

## Capabilities

- `content.strategy.plan`

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
| No gap decisions | Produces no roadmap and says the gap stage must run. |
| Over capacity | The overflow is backlog, stated. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. schedules fixes before new pages;
2. never exceeds capacity;
3. lists DO_NOTHING topics with their reason.
