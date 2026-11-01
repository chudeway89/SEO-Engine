# PUB-001 — Publishing Agent

## Purpose

Publishes content only when a person approved the asset, its current version passed the quality gate and the policy review, it is prose rather than an outline, and the `cms.publish` action carries the approval policy requires. Publication goes through the brand's connected CMS adapter; with the development adapter the action is recorded in `development_adapter` mode and nothing reaches a real site.

## Inputs

Schema: `PublishingInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id / mission_id` | UUID | The brand and mission. |
| `asset_ids` | list[UUID] | Assets; reviewed and approved ones when empty. |
| `publish` | bool | False proposes actions without executing. |

## Outputs

Schema: `PublishingOutput`.

| Field | Meaning |
| --- | --- |
| `awaiting_editorial_approval / awaiting_action_approval` | What is waiting on a person. |
| `blocked` | Assets a gate stopped, with reasons. |
| `published` | External id, link and the adapter mode. |

## Capabilities

- `content.publish`
- `cms.publish`

## Tools

- `cms`
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

`high`.

## Approval

`cms.publish` is listed in `approval_required_for` and is never autonomous. It executes only an action that carries the approval policy requires, and the decision service re-checks that approval at the moment of execution.

## Failure modes

| Mode | Behaviour |
| --- | --- |
| No connected CMS | Publishes nothing and says so. |
| A new version after approval | Back to draft; not published. |
| CMS error | The action is marked failed with the provider's message. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. publishes nothing without editorial and action approval;
2. refuses an approved asset whose new version is unreviewed;
3. records development-adapter publication as such.
