# BRD-002 — Brand Profile Agent

## Purpose

Compares the customer's brand profile with what the crawled website says: declared services and locations no page covers, service and location pages the profile does not mention, and the vocabulary the site leads with. Crawled text is untrusted data — compared and counted, never followed — and every difference is a proposal for the customer. The brand graph is never changed (`brand_graph_changed` is always false).

## Inputs

Schema: `BrandProfileInput` (`schemas.py`).

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id` | UUID | The brand whose profile is compared. |
| `website_id` | UUID \| None | The crawled website to compare against. |

## Outputs

Schema: `BrandProfileOutput`.

| Field | Meaning |
| --- | --- |
| `covered` | Declared items a crawled page covers, with the page. |
| `proposals` | `declared_not_found` and `found_not_declared` differences, each with its URL. |
| `vocabulary` | Terms recurring across titles and H1s. |
| `brand_graph_changed` | Always false. |

## Capabilities

- `brand.profile.review`

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
| No crawl yet | Returns a limitation; nothing is compared. |
| Profile declares nothing | Says there is nothing to confirm. |

Nothing here is hidden, faked or skipped on failure: the run records the error,
and the agent reports a limitation rather than fabricating a result.

## Evaluation criteria

Behavioural tests assert that the agent:

1. leaves the brand graph unchanged;
2. reports declared services the site does not describe;
3. cites the crawl comparison as evidence for every proposal.
