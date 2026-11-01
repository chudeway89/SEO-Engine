# CNT-004 — Content Writer Agent

## Purpose

Writes each open brief as an internal draft. It works with any connected model and with none: with a model, `generate_draft` writes prose within the brief's constraints and the run reports itself hybrid; with none — or if the connected model fails — the draft is a structured outline carrying a notice that it is not prose, and the run says why. The asset's identity comes from the brief, not the model's wording, so a model connected later upgrades an outline in place. It never overwrites written prose and never touches a published page. Each draft is an immutable version created through the content service.

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
| No model | Outlines only, stated as a limitation; a person writes the piece over the outline (`POST /content/{id}/versions` or the content screen) and asks for review. |
| Connected model fails, is misconfigured or returns nothing usable | The outline is produced instead and the limitation gives the reason; the failed call is recorded in `llm_usage`. |
| Model output cut off at the output limit | The draft is kept and flagged as possibly incomplete. |
| The brief's asset already holds prose, or is published | Left untouched and reported in `skipped`; live pages change through CNT-006. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. never generates prose without a model, and completes without one;
2. works with any connected model, and degrades to the outline when it fails;
3. never overwrites written prose or a published page;
4. declares content.create and requires no approval for it;
5. reports hybrid synthesis only when a model wrote.
