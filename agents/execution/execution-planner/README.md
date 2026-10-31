# EXE-001 — Execution Agent

## Purpose

Turns approved recommendations into concrete actions and executes only those that are already approved. It never decides strategy and never grants its own permission: every action it proposes passes through the policy engine, and it refuses to execute anything whose approval requirement has not been met — the domain service raises and the agent reports the block rather than working around it.

## Inputs

Schema: `ExecutionPlanInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id` | UUID | The brand. |
| `mission_id` | UUID \| None | The mission the actions belong to. |
| `execute_approved` | bool | Whether to execute already-approved actions in this run (default true). |

## Outputs

Schema: `ExecutionPlanOutput`.

| Field | Meaning |
| --- | --- |
| `actions_proposed / actions_awaiting_approval / actions_executed` | The disposition of every action. |
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
| No executor implemented for the action type | Recorded as a limitation; the action stays approved and pending, not falsely marked done. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. executes only actions that are already approved;
2. leaves every approval-required action awaiting approval, unexecuted;
3. surfaces a policy refusal as a blocked action with its reason;
4. proposes only action types its manifest declares, or the validator rejects the result.
