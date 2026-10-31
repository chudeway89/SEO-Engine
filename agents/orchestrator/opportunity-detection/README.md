# OPP-001 — Opportunity Detection Agent

## Purpose

Turns the observations the upstream stages produced — technical findings, content decisions, recoverable queries — into evidence-backed opportunities. It detects nothing on its own: an opportunity exists only where an upstream stage observed something that justifies it, and each one carries the evidence it came from.

## Inputs

Schema: `OpportunityDetectionInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id` | UUID | The brand. |
| `website_id` | UUID \| None | Used to read stored technical issues and commercial pages. |
| `mission_id` | UUID \| None | The mission the opportunities belong to. |

## Outputs

Schema: `OpportunityDetectionOutput`.

| Field | Meaning |
| --- | --- |
| `opportunities_detected` | How many were created. |
| `by_type / by_source` | Opportunities grouped by type and by the upstream stage that sourced them. |
| `opportunities` | Each with its impact, effort, confidence and the evidence it cites. |

## Capabilities

- `opportunity.detect`

## Tools

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

`low`.

## Approval

None required. `approval_required_for` is empty, so the result validator rejects any action this agent attempts to propose.

## Failure modes

| Mode | Behaviour |
| --- | --- |
| No upstream observation | Returns a limitation that nothing observable justifies work right now — a result, not an error. |
| Only a technical audit ran | Detects only technical opportunities; makes no claim about content or demand it did not see. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. creates an opportunity only where an upstream stage produced an observation;
2. attaches the sourcing evidence to every opportunity;
3. produces none, with a limitation, when no stage observed anything;
4. never emits an opportunity from a DO_NOTHING content decision.
