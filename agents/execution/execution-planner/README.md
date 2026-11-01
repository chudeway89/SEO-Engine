# EXE-001 — Execution Agent

## Purpose

Turns approved recommendations into concrete actions and executes only those that are already approved. It never decides strategy and never grants its own permission: every action it proposes passes through the policy engine, and an action type its manifest lists under `approval_required_for` waits for a person whatever policy allows (the approval floor). An approved `seo.metadata_update` (page title) or `seo.internal_link_add` is applied through the brand's connected CMS exactly as specified by the change the recommendation carries; nothing is inferred. A change with no concrete specification, or of a kind with no safe general executor (structured data, redirects), is reported and left approved for a person.

## Inputs

Schema: `ExecutionPlanInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id` | UUID | The brand. |
| `mission_id` | UUID \| None | The mission the actions belong to. |
| `execute_approved` | bool | Whether to execute already-approved actions in this run (default true). |
| `draft` | dict \| None | A written draft (`title`, `body_markdown`, …) for a draft action; without one no CMS draft is created. |

## Outputs

Schema: `ExecutionPlanOutput`.

| Field | Meaning |
| --- | --- |
| `actions_proposed / actions_awaiting_approval / actions_executed / actions_settled` | The disposition of every action; settled actions are never re-run. |
| `executed` | What each executed action changed: page, field, before and after, and the integration mode. |
| `not_executable` | Approved actions left for a person, with the reason. |
| `blocked` | Actions the policy engine refused, with the reason. |
| `actions` | Each action with its status, approval requirement and policy decision. |

## Capabilities

- `execution.plan`
- `cms.draft`

## Tools

- `cms`
- `memory`

## Memory

- **Scopes:** `brand`, `mission`
- Writes are confined to those scopes; the runtime refuses any memory access a
  scope here does not grant.

## Permissions

Resolved as the intersection of this manifest and the calling principal. The
agent runs through the Agent Runtime and reaches data only through tenant-scoped
domain services — never the database directly (Rule 4).

## Risk

`medium`.

## Approval

Creating an internal draft is the only autonomous action. Every action that touches the live site — publish, metadata, internal links, schema, redirects, content updates — is listed in `approval_required_for` and cannot execute until a human approves it.

## Failure modes

| Mode | Behaviour |
| --- | --- |
| No recommendations to plan | Returns a limitation; produces no actions. |
| Action needs approval it does not have | Left awaiting approval; never executed. |
| Policy refuses the action | Recorded as blocked with the reason; the agent does not retry around the policy. |
| Approved change has no concrete specification, or no executor exists | Reported in `not_executable`; the action stays approved, never marked failed or done. |
| No CMS connected, or the page is not found in it | Reported with the reason; nothing is applied. |
| Development CMS connected | The change is recorded in `development_adapter` mode and the limitations say nothing reached a real website. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. executes only actions that are already approved;
2. leaves every approval-required action awaiting approval, unexecuted, even where policy alone would allow it;
3. applies exactly the specified change and records before and after;
4. never creates an empty CMS draft and never invents an unspecified change;
5. surfaces a policy refusal as a blocked action with its reason;
6. proposes only action types its manifest declares, or the validator rejects the result.
