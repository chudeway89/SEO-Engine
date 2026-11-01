# CNT-008 — Content Repurposing Agent

## Purpose

Derives platform assets from canonical pieces that passed the quality gate with `repurpose`; each names its canonical source and carries its own audience, objective, format, tone and call to action, and is stored as a draft. Outlines and unreviewed drafts are never repurposed.

## Inputs

Schema: `ContentRepurposingInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id` | UUID | The brand. |
| `asset_ids` | list[UUID] | Canonical pieces; reviewed pieces when empty. |
| `platforms` | list[str] | Supported platforms; unknown ones ignored and stated. |

## Outputs

Schema: `ContentRepurposingOutput`.

| Field | Meaning |
| --- | --- |
| `items` | Per derivative: platform, status (draft), canonical source. |

## Capabilities

- `content.write.repurpose`

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
| Outline or unreviewed piece | Skipped with the reason. |
| Unsupported platform | Ignored and stated. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. names the canonical source on every derivative;
2. skips outlines;
3. stores derivatives as drafts.
