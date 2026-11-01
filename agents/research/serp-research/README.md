# RES-002 — SERP Research Agent

## Purpose

Fetches the results page for each priority query through the SERP integration (raw response stored, API key never stored), persists the snapshot, records people-also-ask questions, and summarises features, recurring domains, the brand's own position and intent shifts. With no SERP key the development adapter returns synthetic `*.example` pages and every snapshot, figure and evidence record is labelled synthetic.

## Inputs

Schema: `SERPResearchInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id / website_id` | UUID | The brand and its site (for its own domain). |
| `queries` | list[str] | Queries to observe; falls back to the top non-branded keywords. |
| `max_queries` | int | Bound on paid lookups (default 10). |
| `country / device` | str | Passed to the provider. |

## Outputs

Schema: `SERPResearchOutput`.

| Field | Meaning |
| --- | --- |
| `landscape` | Feature frequency, recurring domains, brand positions and visible share, intent shifts. |
| `queries_failed` | Lookups that failed, with the provider's reason. |
| `synthetic` | True when any page came from the development adapter. |

## Capabilities

- `seo.serp.research`

## Tools

- `serp`
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
| SERP integration not connected | Observes nothing; a limitation says nothing was estimated. |
| A lookup fails (auth, rate limit) | That query is reported failed; nothing is assumed about it. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. labels synthetic pages synthetic in output, evidence and storage;
2. stores nothing and claims nothing without the integration;
3. records people-also-ask questions with the page's provenance.
