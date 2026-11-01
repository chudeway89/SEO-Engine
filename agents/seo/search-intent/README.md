# SEO-004 — Search Intent Agent

## Purpose

Compares each mapped query's intent — refined by observed SERP features where they exist — with the type of page answering it, classified from URL, title and structured data with the deciding signal named. A page whose type cannot be identified is never reported as a mismatch. Mismatches become content-update seeds naming the page type that would serve the intent.

## Inputs

Schema: `SearchIntentInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id / website_id` | UUID | The brand and its crawled site. |
| `max_findings` | int | Bound. |

## Outputs

Schema: `SearchIntentOutput`.

| Field | Meaning |
| --- | --- |
| `assessments` | Per page: page type and signal, intent, fit, recommended type. |
| `serp_refined / serp_synthetic` | Whether SERP features refined intent, and whether they were synthetic. |

## Capabilities

- `seo.search.intent`

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
| No SERP data | Uses lexical intent alone and says so. |
| Synthetic SERP | Evidence from refined fits is labelled synthetic. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. flags a transactional query answered by an article;
2. asserts nothing when the page type is unidentifiable;
3. cites produced evidence on every seed.
