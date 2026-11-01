# CNT-005 — Content Optimisation Agent

## Purpose

Turns each weak, non-blocking criterion in a draft's evaluation into a specific edit — the section to add, the question to answer, the internal link, the structured data, the over-used term — and records each as a tracked repair. The evaluated version is never changed.

## Inputs

Schema: `ContentOptimisationInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id` | UUID | The brand. |
| `asset_ids` | list[UUID] | Drafts; recent drafts when empty. |

## Outputs

Schema: `ContentOptimisationOutput`.

| Field | Meaning |
| --- | --- |
| `edits` | Criterion, edit type, target, proposal, reason. |

## Capabilities

- `content.edit.optimise`

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
| No evaluation of the current version | Proposes nothing for that draft. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. records each edit as a repair;
2. never creates a new version;
3. ties every edit to the brief.
