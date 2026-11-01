# API

The HTTP API is a thin transport over the domain services. It authenticates,
authorises, calls a service or dispatches work, and wraps the result in one
envelope. It contains no agent logic and no SQL.

- **Base URL:** `/api/v1`
- **Interactive docs:** `/docs` (Swagger), `/redoc` (ReDoc)
- **Machine-readable spec:** `/api/v1/openapi.json`
- **Health:** `GET /healthz` (liveness), `GET /readyz` (readiness — the database)

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
| Missions | `/brands/{id}/missions`, `/missions/{id}` | plan a mission, run it (202), read its graph, progress and metrics |
| Agents | `/agents`, `/agents/runs` | the registry and the observable run record |
| Decisions | `/opportunities`, `/recommendations`, `/actions`, `/outcomes` | the decision stack and the human approval actions |
| Platform | `/integrations`, `/memory/search`, `/events`, `/audit` | connect providers, search memory, read the event and audit logs |

See [`walkthrough.md`](walkthrough.md) for the canonical mission end to end, and
[`examples.http`](examples.http) for ready-to-run requests.
