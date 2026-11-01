# SEO-012 — Indexability Agent

## Purpose

Reconciles the sitemap, the crawl, the business's priority landing pages and — when connected — the URLs earning Search Console impressions. Sitemap URLs that cannot be indexed, indexable pages the sitemap omits, priority pages that cannot be indexed (critical), canonicals pointing at non-indexable targets, and earning URLs now non-indexable are reported. Sitemap URLs beyond the crawl's reach are unverified, never assumed broken.

## Inputs

Schema: `IndexabilityInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id / website_id` | UUID | The brand and its crawled site. |
| `max_findings` | int | Bound. |

## Outputs

Schema: `IndexabilityOutput`.

| Field | Meaning |
| --- | --- |
| `states` | Count of each index state. |
| `issues` | Each disagreement with its severity and the priority it affects. |
| `sitemap_unverified` | URLs beyond the crawl, claimed nothing about. |

## Capabilities

- `seo.audit.indexability`

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
| No crawl | Says the audit must run first. |
| No sitemap | Declared intent cannot be compared, and that is stated. |
| Search Console development adapter | The earning-URL comparison is labelled synthetic. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. reports the noindexed URL the sitemap declares;
2. never reports an unreached sitemap URL as an issue;
3. marks a non-indexable priority landing page critical.
