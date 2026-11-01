# CMP-003 — Competitive Gap Agent

## Purpose

Joins competitor coverage (from competitor analysis) with search visibility (from SERP research) and scores each topic by a transparent sum: coverage the brand lacks plus a competitor on page one where the brand is not. Coverage is observed; visibility inherits its SERP's provenance, and a gap resting only on synthetic SERP data never becomes an opportunity.

## Inputs

Schema: `CompetitiveGapInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id / website_id` | UUID | The brand and its site. |
| `keyword_gaps` | list[dict] | Coverage gaps from competitor analysis. |
| `discovered_competitors` | list[str] | Non-synthetic SERP competitors. |

## Outputs

Schema: `CompetitiveGapOutput`.

| Field | Meaning |
| --- | --- |
| `gaps` | Topic, gap types, competitors, positions, score, synthetic flag. |
| `scoring` | The scoring rule, stated. |
| `opportunity_seeds` | Seeds for gaps with an observed basis. |

## Capabilities

- `competitor.gap`

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

None required. `approval_required_for` is empty, so the result validator rejects any action this agent attempts to propose. Its outputs are findings, evidenced opportunity seeds or recommendations; nothing it produces changes the live site.

## Failure modes

| Mode | Behaviour |
| --- | --- |
| No coverage and no SERP data | Assesses nothing and says so. |
| Synthetic visibility only | Reported, labelled, kept out of the opportunity pipeline. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. scores coverage-plus-visibility gaps highest;
2. finds no gap where the brand already outranks;
3. seeds nothing from synthetic visibility alone.
