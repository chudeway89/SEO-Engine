# CMP-001 — Competitor Discovery Agent

## Purpose

Finds the domains that recur in the stored results pages for the brand's queries and compares them with the recorded competitors. New candidates are proposals; recorded competitors never seen in the results are reported as business, not search, competitors. Domains seen only on synthetic pages are reported and never proposed. The brand graph is never changed.

## Inputs

Schema: `CompetitorDiscoveryInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id / website_id` | UUID | The brand and its site. |
| `minimum_appearances` | int | Recurrence threshold (default 2). |

## Outputs

Schema: `CompetitorDiscoveryOutput`.

| Field | Meaning |
| --- | --- |
| `candidates` | Recurring domains not yet recorded, flagged synthetic where so. |
| `recorded_not_observed` | Recorded competitors absent from every page. |

## Capabilities

- `competitor.discover`

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
| No SERP observations | Identifies nobody; nobody is guessed. |
| Synthetic SERP | No candidate is proposed. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. never recommends a synthetic domain;
2. never changes the brand graph;
3. reports recorded competitors that never appear.
