# SEO-005 — Keyword Cluster Agent

## Purpose

Reads the keyword-to-page mapping as architecture: clusters whose keywords map to several URLs, or pages whose titles target the same terms, are cannibalisation (with the page best placed to own the topic); cluster spokes that never link to their hub are found from the observed internal link graph. Consolidation is proposed as a medium-risk seed for the decision gate.

## Inputs

Schema: `KeywordClusterInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id / website_id` | UUID | The brand and its crawled site. |
| `max_findings` | int | Bound. |

## Outputs

Schema: `KeywordClusterOutput`.

| Field | Meaning |
| --- | --- |
| `cannibalisation` | Competing URLs, the basis and the recommended primary. |
| `structures` | Per cluster: hub, spokes, spokes missing the hub link. |

## Capabilities

- `seo.keyword.architecture`

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
| No clusters | Says keyword research must run. |
| No website | Hub-and-spoke linking is not assessed, and that is stated. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. names every competing URL and a primary;
2. reports a spoke that never links to its hub;
3. records derived findings as inferences with capped confidence.
