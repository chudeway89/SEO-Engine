# DEC-001 — Decision Agent

## Purpose

The final strategic reviewer before anything becomes a recommendation. For each prioritised opportunity it asks: is it real, is the evidence sufficient, does an existing asset already solve it, is there a safer action, what could go wrong, and does it need approval. An opportunity that fails those questions is rejected here, with the reason recorded, rather than passed to a human as noise.

## Inputs

Schema: `DecisionInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id` | UUID | The brand. |
| `mission_id` | UUID \| None | The mission the recommendations belong to. |
| `max_recommendations` | int | Upper bound on recommendations produced (default 10). |

## Outputs

Schema: `DecisionOutput`.

| Field | Meaning |
| --- | --- |
| `reviewed / recommended` | How many opportunities were reviewed and how many became recommendations. |
| `rejected` | Each rejected opportunity with the reason it did not meet the bar. |
| `recommendations` | Each with its evidence, expected outcome, risk and approval requirement. |

## Capabilities

- `decision.recommend`

## Tools

- `memory`

## Memory

- **Scopes:** `tenant`, `brand`, `mission`
- Writes are confined to those scopes; the runtime refuses any memory access a
  scope here does not grant.

## Permissions

Resolved as the intersection of this manifest and the calling principal. The
agent runs through the Agent Runtime and reaches data only through tenant-scoped
domain services — never the database directly (Rule 4).

## Risk

`medium`.

## Approval

This agent sets the approval requirement on the recommendations it produces, from the brand's risk category and each action's risk. It proposes no actions itself, so its own `approval_required_for` is empty.

## Failure modes

| Mode | Behaviour |
| --- | --- |
| No prioritised opportunities | Returns a limitation; recommends nothing. |
| An opportunity cites too little evidence | Rejected with that reason, not forwarded as a weak recommendation. |
| A health/medical/financial brand | Content recommendations carry a mandatory approval requirement and reason. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. produces a recommendation only when the opportunity is real and sufficiently evidenced;
2. records a reason for every rejection;
3. attaches evidence and an expected outcome to every recommendation (Rule 7);
4. sets the approval requirement from the brand's risk category and the action's risk, never bypassing it.
