# SEO-006 — Content Gap Agent

## Purpose

For each topic cluster it decides exactly one of CREATE, UPDATE, CONSOLIDATE, REDIRECT or DO_NOTHING, and records why. The decision order is deliberately biased against publishing: competing pages are consolidated, a good page is left alone, a weak one is updated, and a new page needs a stated reason. A keyword on its own is never a reason to publish (Rule 13).

## Inputs

Schema: `ContentGapInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id` | UUID | The brand whose clusters are evaluated. |
| `website_id` | UUID \| None | The brand's crawled pages, for coverage and quality. |
| `max_clusters` | int | Upper bound on clusters evaluated (default 25). |

## Outputs

Schema: `ContentGapOutput`.

| Field | Meaning |
| --- | --- |
| `clusters_evaluated` | How many topic clusters were considered. |
| `decisions` | Count of each decision type, DO_NOTHING included. |
| `gaps` | Per-topic decision, reason, coverage and the target URL where one applies. |

## Capabilities

- `seo.content.gap`

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

None required. `approval_required_for` is empty, so the result validator rejects any action this agent attempts to propose.

## Failure modes

| Mode | Behaviour |
| --- | --- |
| No clusters exist | Returns a limitation that keyword research must run first; decides nothing. |
| No crawled pages | Flags every decision provisional, because without the brand's own pages every topic looks uncovered. |
| A topic has demand, coverage and SERP evidence all absent | Returns DO_NOTHING — a result, not a gap. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. returns exactly one decision per cluster, with a reason;
2. prefers CONSOLIDATE over CREATE when the brand already has competing pages on the topic;
3. returns DO_NOTHING for a topic with no demand, no competitor coverage and no SERP evidence;
4. marks decisions provisional when no crawl is available.
