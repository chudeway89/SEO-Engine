# QUAL-001 — Quality Guardian Agent

## Purpose

Audits every recommendation for the brand against the evidence store as it now stands: dangling references, a basis made entirely of synthetic data, confidence beyond the strongest evidence or beyond the hypothesis cap on an inference-only basis, high-risk changes without approval, missing expected outcomes and duplicates. It reports and scores; it does not rewrite another agent's work.

## Inputs

Schema: `QualityAuditInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id` | UUID | The brand. |
| `mission_id` | UUID \| None | Scope to one mission. |

## Outputs

Schema: `QualityAuditOutput`.

| Field | Meaning |
| --- | --- |
| `by_rule / issues` | Issues by rule, each naming the recommendation. |
| `quality_score` | Share without a high or critical issue. |

## Capabilities

- `recommendation.audit`

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

None required. `approval_required_for` is empty, so the result validator rejects any action this agent attempts to propose. Its outputs are findings, evidenced opportunity seeds or recommendations; nothing it produces changes the live site.

## Failure modes

| Mode | Behaviour |
| --- | --- |
| No recommendations | Audits nothing and says so. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. flags recommendations resting only on synthetic evidence;
2. flags dangling evidence references;
3. finds no dangling evidence after a full mission.
