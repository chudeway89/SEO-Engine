# ANA-002 — GA4 Analytics Agent

## Purpose

Syncs Analytics and establishes the organic qualified-lead baseline the mission measures itself against. When no baseline can be measured it says so and leaves the mission without one — a mission that starts from an invented baseline would report invented progress.

## Inputs

Schema: `AnalyticsInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id` | UUID | The brand to analyse. |
| `days` | int | Lookback window in days (default 28). |

## Outputs

Schema: `AnalyticsOutput`.

| Field | Meaning |
| --- | --- |
| `connected / mode / provenance` | Whether GA4 is connected, in which mode, and the provenance of its data. |
| `traffic_rows / conversion_rows` | Volume of synced data. |
| `organic_lead_baseline` | The measured baseline, or null when none could be established. |
| `baseline_provenance / baseline_source` | How the baseline was obtained; synthetic in development mode. |

## Capabilities

- `analytics.ga4.read`

## Tools

- `ga4`
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

None required. `approval_required_for` is empty, so the result validator rejects any action this agent attempts to propose.

## Failure modes

| Mode | Behaviour |
| --- | --- |
| GA4 not connected | Returns connected=false and a limitation; the mission runs with no baseline rather than a guess. |
| No organic conversion events | baseline is null, with a limitation; progress against a target cannot be computed. |
| Development-adapter mode | Completes, but the baseline and every figure are labelled synthetic. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. establishes a baseline only from measured organic conversion events;
2. leaves the baseline null, with a limitation, when none exists;
3. labels the baseline synthetic when running on the development adapter;
4. never fabricates a conversion figure to fill the gap.
