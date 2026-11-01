# CNT-002 — Content Research Agent

## Purpose

Builds a research pack per scheduled topic from evidence already held: stored audience questions, the topic's services and cluster keywords, the observed results page (with its provenance) and registered sources with tier and verification. It searches nothing new and generates nothing; a thin pack says what it lacks.

## Inputs

Schema: `ContentResearchInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id / website_id` | UUID | The brand and its site. |
| `topics` | list[dict] | Roadmap items. |
| `max_topics` | int | Bound. |

## Outputs

Schema: `ContentResearchOutput`.

| Field | Meaning |
| --- | --- |
| `packs` | Per topic: research id, questions, entities, source URLs, gaps, evidence ids. |

## Capabilities

- `content.research`

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
| No topics | Builds nothing; says the strategist must run. |
| Thin research | The pack lists what is missing. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. stores a research record per topic;
2. reports missing verified sources;
3. invents no question or source.
