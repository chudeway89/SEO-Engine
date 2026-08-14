# BRD-001 — Brand Understanding Agent

## Purpose

Builds the platform's working model of a brand from the brand graph the customer
supplied, and reports honestly on what is missing. Every downstream agent —
keyword research, competitor analysis, content strategy, prioritisation — reads
this model, so a fabricated fact here would silently corrupt everything after
it. The agent therefore never infers a service, audience or location that the
customer did not state.

It is the first agent in the "Increase qualified organic leads" task graph.

## Inputs

| Field | Type | Notes |
| --- | --- | --- |
| `brand_id` | UUID | Must belong to the calling tenant; enforced by the brand service. |

Schema: `BrandUnderstandingInput` (`schemas.py`).

## Outputs

Schema: `BrandUnderstandingOutput`.

| Field | Meaning |
| --- | --- |
| `completeness` | Per-dimension coverage of the brand graph, with the reason each dimension matters. |
| `completeness_score` | 0–100 mean of dimension ratios. Not a quality score — a coverage score. |
| `commercial_priorities` | Services and products ordered by revenue weight, priority, and whether a stated goal names them. |
| `seed_topics` | Research seeds, derived only from supplied services, products, audience vocabulary, pains and locations. |
| `approved_claims` / `prohibited_claims` | Claim constraints the content agents must respect. |
| `missing_inputs` | Dimensions below their expected minimum. Each also becomes a stated limitation. |

## Capabilities

- `brand.understand`
- `brand.profile`
- `memory.write`

## Tools

- `memory` — writes the brand profile to brand-scoped memory so later runs and
  later missions inherit it. If the tool is unavailable the agent still
  completes and records the loss as a limitation.

## Memory

- **Scopes read:** `brand`, `tenant`
- **Writes:** one `brand_fact` memory keyed `brand:profile`, importance 0.9, no
  expiry, carrying the structured profile and citing the brand-graph evidence.

## Permissions

Requires `brand.read` on the calling principal. A viewer can run it; the agent
performs no writes outside memory.

## Risk

`low`. The agent reads the customer's own data, makes no external requests,
proposes no actions and requires no approval.

## Approval

None required. `approval_required_for` is empty, so the validator will reject
any action this agent tries to propose.

## Failure modes

| Mode | Behaviour |
| --- | --- |
| Brand does not exist, or belongs to another tenant | `NotFoundError` from the brand service; the run is recorded as failed. 404 rather than 403, so tenant membership is not disclosed. |
| Brand graph is empty | Completes with a low completeness score and one limitation per missing dimension. It does **not** invent placeholder services or audiences. |
| `memory` tool unavailable | Completes; records the limitation; downstream runs simply do not inherit the profile. |
| High-risk brand with no approved claims | Completes and records a limitation warning that commercial content generation is constrained. |

## Evaluation criteria

Behavioural tests assert that the agent:

1. reports every supplied service, audience and location, and no others;
2. produces zero seed topics from an empty brand graph, rather than inventing them;
3. lowers `completeness_score` and raises a limitation for each missing dimension;
4. ranks a service named in a stated business goal ahead of a heavier-weighted
   service that no goal mentions;
5. surfaces prohibited claims so the content pipeline can enforce them;
6. writes exactly one brand-scoped memory, citing evidence.

Golden dataset: `tests/evaluation/golden/brand_understanding.json`.
