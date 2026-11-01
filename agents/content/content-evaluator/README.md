# CNT-007 — Content Evaluator Agent

## Purpose

Scores each draft's current version against its brief on twelve criteria with `evaluate_content`; accuracy, risk, brand alignment and search intent block whatever the average. Every evaluation is recorded against the exact version it judged.

## Inputs

Schema: `ContentEvaluatorInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id` | UUID | The brand. |
| `asset_ids` | list[UUID] | Drafts to evaluate; recent drafts when empty. |

## Outputs

Schema: `ContentEvaluatorOutput`.

| Field | Meaning |
| --- | --- |
| `evaluations` | Per draft: version, score, passed, blocking failures. |

## Capabilities

- `content.evaluate`

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
| No brief recorded | Skipped with the reason. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. records the evaluation against the version it judged;
2. skips a draft with no brief;
3. fails a draft on any blocking criterion.
