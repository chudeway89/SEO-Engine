# API

The HTTP API is a thin transport over the domain services. It authenticates,
authorises, calls a service or dispatches work, and wraps the result in one
envelope. It contains no agent logic and no SQL.

- **Base URL:** `/api/v1`
- **Interactive docs:** `/docs` (Swagger), `/redoc` (ReDoc)
- **Machine-readable spec:** `/api/v1/openapi.json`
- **Health:** `GET /healthz` (liveness), `GET /readyz` (readiness — the database;
  it also reports which language model, if any, is in use, and why a configured
  one is not usable — a model is never a readiness condition)

## The envelope

Every success:

```json
{ "data": { ... }, "meta": { ... }, "request_id": "req_a1b2c3d4" }
```

Every failure:

```json
{ "error": { "code": "NOT_FOUND", "message": "...", "details": {} },
  "request_id": "req_a1b2c3d4" }
```

The `request_id` is on both paths and in the `x-request-id` header. Quote it in
a bug report and an operator can find the exact run in the logs. List endpoints
put pagination in `meta` (`limit`, `offset`, `count`, `total`, `has_more`).

## Authentication

A Bearer token from `/api/v1/auth/login` (or `/auth/register`). Send it as
`Authorization: Bearer <access_token>`. The token carries the tenant; every
service built from it is tenant-scoped, so the HTTP boundary cannot read across
tenants.

## Conventions

- **Slow work returns 202.** A crawl or a mission run is dispatched to the Agent
  Runtime or the workflow engine in the background; the response gives you the
  identifiers to poll. Nothing slow runs inside a request.
- **Metrics carry provenance.** A figure the platform could not measure is
  `null` with a stated reason, never an estimate. Development-mode integration
  data is labelled synthetic in the response.
- **Errors are typed.** `VALIDATION_ERROR` (422), `UNAUTHENTICATED` (401),
  `FORBIDDEN` (403), `NOT_FOUND` (404), `CONFLICT` (409), `RATE_LIMITED` (429),
  `CONFIGURATION_ERROR` (503), `INTERNAL_ERROR` (500). A cross-tenant request
  for an existing resource returns 404, not 403, so membership is not disclosed.
- **Rate limits.** A sliding window per credential (or client address before
  auth), with `Retry-After` and `x-ratelimit-*` headers.

## Endpoint groups

| Group | Prefix | What it does |
| --- | --- | --- |
| Auth | `/auth` | register, login, refresh, `me` |
| Tenant | `/tenant` | the tenant, members, role changes |
| Brands | `/brands` | the brand graph: brand, goals, services, products, audiences, locations, competitors, voice, claims, profile |
| Websites | `/brands/{id}/websites`, `/websites/{id}` | add a site, start an audit (202), list crawls, pages, issues, scorecard |
| Search | `/brands/{id}/keywords`, `/keyword-clusters` | derived keywords and clusters (read) |
| Missions | `/brands/{id}/missions`, `/missions/{id}`, `/brands/{id}/strategy` | plan a mission, run it (202), read its graph, progress and metrics; preview a plan through ORCH-001 without creating a mission |
| Agents | `/agents`, `/agents/runs` | the registry and the observable run record |
| Decisions | `/opportunities`, `/recommendations`, `/actions`, `/outcomes` | the decision stack and the human approval actions |
| Content | `/brands/{id}/content`, `/brands/{id}/sources`, `/content/{id}` | content assets with versions, current-version evaluations, repairs and derivatives; the source register; the human writing path and editorial decision (below) |
| Platform | `/brands/{id}/integrations`, `/memory/search`, `/events`, `/audit` | connect and disconnect providers, search memory, read the event and audit logs |

## The human writing path

Without a language model the writer agent (CNT-004) leaves a structured outline,
never invented prose, and the quality gate blocks it. A person closes the loop:

| Step | Request | What happens |
| --- | --- | --- |
| Write | `POST /content/{id}/versions` | Records a new immutable version attributed to the user and labelled `synthesis_mode: "human"`. The body's `##` headings become its sections unless `sections` are given. `cited_source_urls` must come from the brand's source register (`GET /brands/{id}/sources`); omitted, the previous version's citations carry over. A body that still carries the outline notice is refused (422): submitting the outline unchanged is not writing it. Any new version returns the asset to draft. |
| Review | `POST /content/{id}/review` | Runs the evaluator (CNT-007), the quality gate (CNT-009) and the policy guardian (POL-001) through the Agent Runtime against the current version, and returns each run's summary, output and limitations. A pass moves the asset to `in_review`; nothing is approved. Only a draft is reviewed (409 otherwise). |
| Approve | `POST /content/{id}/approve` | A person's decision. Refused (409) unless the *current* version passed the gate: a pass recorded against an earlier version does not count. |
| Publish | `POST /content/{id}/publish` | Runs the publishing agent (PUB-001). Where policy or the agent's manifest requires approval, the `cms.publish` action waits (`awaiting_action_approval` in the output); approve it with `POST /actions/{id}/approve` and publish again. With the development CMS the run's limitations say nothing reached a real site. |

The reviewing and publishing agents run synchronously inside the request; they
are deterministic and fast. `DELETE /brands/{id}/integrations/{provider}`
revokes a connection and destroys its stored credentials; the row is kept,
marked `revoked`, so history synced through it stays attributable.

See [`walkthrough.md`](walkthrough.md) for the canonical mission end to end, and
[`examples.http`](examples.http) for ready-to-run requests.
