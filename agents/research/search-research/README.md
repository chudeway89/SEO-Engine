# RES-001 — Search Research Agent

## Purpose

Describes the demand the site is measured against from Search Console rows only: branded versus non-branded share, intent and topic mix, question share, and the queries in striking distance. The weakest provenance among the rows labels the whole landscape, and the permanent limitation is stated every time: demand the site is invisible to is absent and not estimated.

## Inputs

Schema: `SearchResearchInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id` | UUID | The brand. |
| `max_queries` | int | Rows read (default 500). |

## Outputs

Schema: `SearchResearchOutput`.

| Field | Meaning |
| --- | --- |
| `measured` | False when Search Console is unavailable or empty. |
| `provenance` | observed, synthetic_demo or unknown. |
| `landscape` | Impressions, clicks, shares, intent and band splits, top topics, striking distance. |

## Capabilities

- `research.search.demand`

## Tools

- `gsc`
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
| Search Console not connected | No figures; a limitation says nothing was estimated. |
| Connected but not synced | No figures; says so. |
| Development adapter | Every figure labelled synthetic. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. carries the rows' provenance into the landscape;
2. always states the visibility limitation;
3. produces no landscape at all without Search Console.
