# CMP-002 — Competitor Analysis Agent

## Purpose

Crawls the competitors the customer actually recorded, within the same safeguards as the brand's own crawl, and compares topical coverage. Everything it asserts is grounded in pages it fetched; a competitor it could not reach produces no gaps — the failure is reported as a limitation, never as an absence of coverage on the competitor's side.

## Inputs

Schema: `CompetitorAnalysisInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id` | UUID | The brand whose competitors are analysed. |
| `website_id` | UUID \| None | The brand's own pages, for comparison. |
| `keywords` | list[str] | Keywords to test for competitor-only coverage. |
| `max_competitors` | int | Upper bound on competitors crawled (default 5). |

## Outputs

Schema: `CompetitorAnalysisOutput`.

| Field | Meaning |
| --- | --- |
| `competitors_analysed / competitors_unreachable` | Who was and was not successfully crawled. |
| `pages_observed` | Total indexable competitor pages seen. |
| `keyword_gaps` | Keywords a competitor page addresses and no observed brand page does. |
| `competitor_pages` | The observed URLs per competitor, handed to the content-gap stage. |

## Capabilities

- `competitor.analyse`
- `website.crawl`

## Tools

- `crawler`
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
| No competitors recorded | Returns a limitation; asserts nothing about the landscape. |
| A competitor is unreachable | Added to competitors_unreachable with a limitation; no coverage is claimed for it either way. |
| `crawler` tool not granted | Returns without fetching anything and says so. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. crawls only recorded competitors, within the shallow page and depth caps;
2. reports an unreachable competitor as a limitation, not as having no content;
3. asserts a keyword gap only when a fetched competitor page covers it and no brand page does;
4. promotes a business competitor to a content competitor only once its content is observed.
