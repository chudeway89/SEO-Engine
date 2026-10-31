# SEO-003 — Keyword Intelligence Agent

## Purpose

Runs the keyword pipeline over the brand graph and whatever measured demand is actually connected. Its most important behaviour is what it does not do: with no keyword-volume provider connected, it produces keywords with no volume figure and says so, rather than estimating a number that would propagate through every downstream score (Rule 14).

## Inputs

Schema: `KeywordResearchInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id` | UUID | The brand to research. |
| `website_id` | UUID \| None | If present, keywords are mapped to existing pages. |
| `max_keywords` | int | Upper bound on derived keywords (default 300). |

## Outputs

Schema: `KeywordResearchOutput`.

| Field | Meaning |
| --- | --- |
| `keywords_total / clusters_total` | How many keywords and topic clusters were derived. |
| `measured_demand_available` | True only when Search Console returned observed queries. |
| `sources_used` | Always includes brand_graph; adds google_search_console only if connected. |
| `top_keywords` | Each with its opportunity score, intent, mapped URL, and which dimensions had observed data. |
| `intent_distribution` | Counts by primary intent. |

## Capabilities

- `seo.keyword.research`
- `seo.keyword.cluster`
- `seo.search.intent`

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

None required. `approval_required_for` is empty, so the result validator rejects any action this agent attempts to propose.

## Failure modes

| Mode | Behaviour |
| --- | --- |
| No search-data provider connected | Every keyword carries no volume; the demand dimension contributes zero, not an estimate, and a limitation says so. |
| Brand graph empty | Returns with a limitation that there is nothing to derive keywords from. No keywords are invented. |
| `search` service absent | Derives keywords in memory and returns them without persisting; still honest about demand. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. derives keywords from services, products and audience vocabulary, and none from thin air;
2. attaches a measured demand dimension only to queries Search Console actually returned;
3. omits any volume figure, and records the limitation, when no provider is connected;
4. clusters related keywords and assigns a primary intent to each.
