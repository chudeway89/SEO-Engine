# POL-001 — Policy Guardian Agent

## Purpose

Checks drafts against the brand's prohibited claims, the voice profile's forbidden terminology, statements resting on unverified sources and absolute outcome language in regulated categories — excluding the brief's own quoted prohibitions — and re-evaluates pending and approved actions against current policy, reporting any that policy would now block or send for approval.

## Inputs

Schema: `PolicyReviewInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id / mission_id` | UUID | The brand and mission. |
| `asset_ids` | list[UUID] | Drafts; recent drafts and reviews when empty. |

## Outputs

Schema: `PolicyReviewOutput`.

| Field | Meaning |
| --- | --- |
| `content` | Per draft: compliant and violations. |
| `actions_needing_attention` | Open actions current policy would block or gate. |

## Capabilities

- `policy.evaluate`

## Tools

- `policy`
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

It proposes no action. It records a policy review per draft version, returns a non-compliant in-review draft to draft, and reports open actions current policy would block; the execution gate re-checks approval at the moment of execution.

## Failure modes

| Mode | Behaviour |
| --- | --- |
| Nothing to review | Says so. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. returns a draft with a prohibited claim to draft;
2. ignores prohibitions the brief quotes to the writer;
3. reports an action current policy would block.
