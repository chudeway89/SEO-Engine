# CNT-003 — Content Brief Agent

## Purpose

Writes the definitive brief per researched topic with `build_brief`: keywords from its cluster, intent, audience, required sections, questions, verified sources only (unverified ones become claims requiring verification), internal links to crawled pages, approved claims and prohibited claims — with additional prohibitions in regulated categories. A topic whose cluster cannot be found is skipped with the reason.

## Inputs

Schema: `ContentBriefInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id / website_id` | UUID | The brand and its site. |
| `research` | list[dict] | Research packs. |
| `max_briefs` | int | Bound. |

## Outputs

Schema: `ContentBriefOutput`.

| Field | Meaning |
| --- | --- |
| `briefs` | Brief id, title, keyword, risk category, evidence ids. |

## Capabilities

- `content.write.brief`

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
| No matching cluster | Skipped with the reason; no keywords are invented. |
| No verified source | A finding warns the writer. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. carries the brand's prohibited claims into every brief;
2. offers only verified sources for citation;
3. skips a topic with no cluster rather than inventing keywords.
