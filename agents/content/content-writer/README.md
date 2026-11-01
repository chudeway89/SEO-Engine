# CNT-004 — Content Writer Agent

## Purpose

Writes the first version of each open brief as an internal draft. With a model configured, `generate_draft` writes prose within the brief's constraints and the run reports itself hybrid; with none, the gateway refuses to improvise and the draft is a structured outline carrying a notice that it is not prose. Each draft is an immutable version created through the content service.

## Inputs

Schema: `ContentWriterInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id / website_id` | UUID | The brand and its site. |
| `brief_ids` | list[UUID] | Briefs to write; open briefs when empty. |
| `max_drafts` | int | Bound. |

## Outputs

Schema: `ContentWriterOutput`.

| Field | Meaning |
| --- | --- |
| `drafts` | Asset, version, brief, outline flag, synthesis mode, word count. |

## Capabilities

- `content.write.draft`

## Tools

- `llm`
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

`medium`.

## Approval

`content.create` — an internal draft record no visitor can see — is its only, declared, autonomous action. It cannot approve or publish: publication is a separate action that PUB-001 proposes and a person approves.

## Failure modes

| Mode | Behaviour |
| --- | --- |
| No open brief | Writes nothing. |
| No model | Outlines only, stated as a limitation. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. never generates prose without a model;
2. declares content.create and requires no approval for it;
3. reports hybrid synthesis only when a model wrote.
