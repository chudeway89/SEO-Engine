# RES-006 — Source and Evidence Agent

## Purpose

Builds the brand's source register from URLs named as the source of approved claims and the external pages the brand's own site links to. Each is tiered by explicit domain rules (§55) and a bounded number are fetched; only a successful fetch verifies a source. Approved claims are checked against the register — a named certificate that was never fetched is `source_named_unverified`, not support. Fetched pages keep only status and title.

## Inputs

Schema: `SourceEvidenceInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id / website_id` | UUID | The brand and its crawled site. |
| `max_fetch` | int | Sources fetched this run (default 8). |

## Outputs

Schema: `SourceEvidenceOutput`.

| Field | Meaning |
| --- | --- |
| `sources` | Each with tier, reliability, verified and the claim it supports. |
| `claims` | Each approved claim: sourced, source_named_unverified or unsourced. |
| `tiers` | Distribution of tiers. |

## Capabilities

- `research.sources`
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

None required. `approval_required_for` is empty, so the result validator rejects any action this agent attempts to propose. Its outputs are findings, evidenced opportunity seeds or recommendations; nothing it produces changes the live site.

## Failure modes

| Mode | Behaviour |
| --- | --- |
| A source does not answer 200 | It stays unverified. |
| More candidates than the bound | The rest stay unverified and that is stated. |
| Regulated category with unsourced claims | High-severity findings and a limitation not to publish. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. verifies a source only after a successful fetch;
2. never treats a reserved test domain as authoritative;
3. does not count a named-but-unfetched source as support.
