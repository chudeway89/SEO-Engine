# CNT-006 — Content Update Agent

## Purpose

For each topic the gap stage decided to UPDATE, builds the brief the page should meet and diffs the live page against it with `build_update_plan`: sections to add or rewrite, unanswered questions, unsupported claims, internal links and metadata changes.

## Inputs

Schema: `ContentUpdateInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id / website_id` | UUID | The brand and its crawled site. |
| `content_gaps` | list[dict] | Decisions from the gap stage. |
| `max_pages` | int | Bound. |

## Outputs

Schema: `ContentUpdateOutput`.

| Field | Meaning |
| --- | --- |
| `plans` | Per page: changes and the full plan, with its brief. |

## Capabilities

- `content.edit.update`

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

It proposes no action itself. Each live-page change is a `content.update` recommendation; in a regulated category it is high risk, so the result requires approval, and nothing changes until a person approves the action the decision chain creates.

## Failure modes

| Mode | Behaviour |
| --- | --- |
| Target page not crawled | Skipped with the reason. |
| Page already meets its brief | No recommendation. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. requires approval for regulated live-page changes;
2. cites only evidence the run can see;
3. skips pages that already meet their brief.
