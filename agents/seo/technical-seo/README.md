# SEO-001 — Technical SEO Agent

## Purpose

Crawls a website within its configured safeguards and runs the deterministic check engine over the result. Every finding is a rule over observed data, so it is reproducible and explainable; the agent interprets which findings matter, it never invents one. Crawled copy stays untrusted throughout — any text that resembles an instruction is reported as a security finding and handled as data, never obeyed (Rule 9).

## Inputs

Schema: `TechnicalAuditInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `website_id` | UUID | The website to audit; must belong to the tenant. |
| `brand_id` | UUID | The owning brand. |
| `max_pages` | int \| None | Crawl cap; falls back to the configured default. |
| `max_depth` | int \| None | Crawl depth cap; falls back to the configured default. |

## Outputs

Schema: `TechnicalAuditOutput`.

| Field | Meaning |
| --- | --- |
| `pages_crawled` | How many pages were actually fetched within the limits. |
| `issues_by_severity` | Deterministic findings counted by severity. |
| `dimensions` | Nine SEO dimensions scored independently; 'not evaluated' is a value. |
| `overall_health` | 0–100 weighted over the dimensions that were evaluated. |
| `ai_search_readiness / agentic_web_readiness` | Scores derived only from observed signals. |
| `stopped_reason` | Why the crawl stopped early, when it did; findings cover only what was crawled. |

## Capabilities

- `seo.audit`
- `website.crawl`
- `seo.indexability`

## Tools

- `crawler`
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
| `crawler` tool not granted | Returns immediately with no findings and says so; it does not fabricate an audit. |
| Crawl stops early (budget, depth, time) | Completes over the pages seen and records a limitation that the site was not fully covered. |
| Page copy contains an injection attempt | Raises a security flag naming the pages and patterns; the copy is stored as untrusted content and never acted on. |
| A dimension cannot be judged from the crawl | That dimension is reported 'not evaluated' with a reason, never scored 100. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. finds the planted defects on the fake site (duplicate titles, missing H1, thin page, noindex, broken link, bad JSON-LD) and no spurious ones;
2. reports the injection page as a security finding rather than following its instruction;
3. scores each of the nine dimensions independently and marks un-observable ones 'not evaluated';
4. returns a limitation, not a guess, when the crawl is truncated.
