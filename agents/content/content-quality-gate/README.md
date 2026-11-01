# CNT-009 — Content Quality Guardian Agent

## Purpose

The gate between a draft and a human approver. It blocks a draft whose current version failed or skipped evaluation, is an outline rather than prose, duplicates another asset or a live page, is thin against its brief, or is one of several near-identical template variants (scaled content). Every block becomes a tracked repair; a pass moves the draft to review and no further.

## Inputs

Schema: `QualityGateInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id / website_id` | UUID | The brand and its site (for duplicate checks). |
| `asset_ids` | list[UUID] | Drafts; recent drafts when empty. |

## Outputs

Schema: `QualityGateOutput`.

| Field | Meaning |
| --- | --- |
| `results` | Per draft: passed, blocking, warnings, requires_human_review (always true). |

## Capabilities

- `content.evaluate.gate`

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

`medium`.

## Approval

It proposes no action. A passing draft moves to `in_review`; the agent-scoped content service refuses to approve content, so approval stays with a person.

## Failure modes

| Mode | Behaviour |
| --- | --- |
| Outline | Blocked with an `outline_needs_prose` repair. |
| Never evaluated | Blocked; the gate does not guess. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. blocks an outline however well it scores;
2. moves a passing draft to review, never to approved;
3. blocks a draft that was never evaluated.
