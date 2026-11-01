# SEO-002 — On-Page SEO Agent

## Purpose

For every page with a keyword mapped to it, scores how clearly the title, H1, meta description, opening copy and URL carry that keyword (0-100, weighted). A corrected title is proposed only from the keyword and brand name; a meta description is never generated — the agent says what it must contain. Misalignments become evidenced opportunity seeds; nothing changes on the site.

## Inputs

Schema: `OnPageInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id / website_id` | UUID | The brand and its crawled site. |
| `max_pages / max_findings` | int | Bounds. |

## Outputs

Schema: `OnPageOutput`.

| Field | Meaning |
| --- | --- |
| `pages` | Per page: score, missing elements, proposed title, meta guidance. |
| `misaligned / average_alignment` | Summary figures. |
| `opportunity_seeds` | On-page seeds citing the page evidence. |

## Capabilities

- `seo.audit.onpage`

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
| No mapped keyword | Says keyword research must run; judges nothing. |
| Mapped pages not crawled | Says none could be assessed. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. judges only pages with a mapped keyword;
2. proposes titles from the keyword and brand name only;
3. cites produced evidence on every seed.
