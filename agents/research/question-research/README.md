# RES-005 — Question Research Agent

## Purpose

Gathers questions from Search Console, people-also-ask and the brand's audience vocabulary, merges duplicates while keeping every source and the weakest provenance, and maps each to the page whose headings (or copy) already answer it. Unanswered questions with measured demand or independent sources become evidenced opportunity seeds; publishing is still decided downstream.

## Inputs

Schema: `QuestionResearchInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id / website_id` | UUID | The brand and its crawled site. |
| `max_questions` | int | Bound (default 100). |

## Outputs

Schema: `QuestionResearchOutput`.

| Field | Meaning |
| --- | --- |
| `questions` | Each with sources, provenance, impressions and answering page. |
| `answered / unanswered` | Counts. |
| `opportunity_seeds` | Evidenced seeds for unanswered questions with enough support. |

## Capabilities

- `research.questions`

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
| No question in any source | Returns a limitation. |
| No crawl | Every question is provisionally unanswered, and that is stated. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. keeps synthetic provenance on questions seen only on synthetic pages;
2. labels audience-vocabulary questions as user-provided;
3. seeds only questions with measured demand or two sources.
