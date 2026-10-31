# ANA-001 — Search Console Analytics Agent

## Purpose

Syncs Search Console performance and surfaces queries whose average position is close enough to the first page that improvement is realistic. Every figure is measured; when Search Console is connected only through the development adapter, every figure is labelled synthetic.

## Inputs

Schema: `SearchConsoleInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id` | UUID | The brand to analyse. |
| `website_id` | UUID \| None | The property, when the brand has more than one site. |
| `days` | int | Lookback window in days (default 28). |

## Outputs

Schema: `SearchConsoleOutput`.

| Field | Meaning |
| --- | --- |
| `connected` | Whether Search Console is connected at all. |
| `rows_synced / total_clicks / total_impressions` | Measured performance over the window. |
| `recoverable_queries` | Queries in the recoverable position band with meaningful impressions. |
| `observed_queries` | Query, impressions, clicks and position, handed to keyword research and opportunity detection. |

## Capabilities

- `analytics.gsc.read`

## Tools

- `gsc`
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
| Search Console not connected | Returns with connected=false and a limitation; no performance is invented. |
| Development-adapter mode | Completes, but every figure is labelled synthetic demonstration data. |
| No query in the recoverable band | Claims no position-based opportunity and says why. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. returns measured clicks, impressions and positions, never estimated ones;
2. flags a query as recoverable only within the position band and above the impression floor;
3. labels every figure synthetic when running on the development adapter;
4. hands observed queries downstream so demand is measured, not assumed.
