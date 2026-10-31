# Security

Security in SEO Engine is structural, not advisory. The properties below are
enforced by code and proven by the tests under `tests/security/` and
`tests/integration/`, not left to reviewer vigilance.

## Tenant isolation

A tenant must never reach another tenant's data, memory, credentials,
recommendations, analytics, content or actions (Rule 10). Three redundant
layers enforce it:

1. **Schema** — every owned table carries a non-nullable `tenant_id`
   (a migration-level invariant, tested).
2. **Repository** — `TenantScopedRepository` predicates every read and write on
   the tenant, refuses to reassign a row's `tenant_id`, and refuses to rebind
   its session.
3. **Session guard** — a `before_flush` listener raises `TenantIsolationError`
   if any dirty row carries a tenant other than the session's.

The single hand-written SQL path, semantic memory search, re-asserts the tenant
predicate on both joined tables. Across the HTTP boundary a fully-authenticated
tenant requesting another tenant's resource receives `404`, not `403`, so
membership is never disclosed.

## Authentication and authorisation

- Bearer tokens via a provider abstraction (`JWTAuthProvider` today; OAuth/OIDC
  later behind the same interface). The API never decodes a token itself.
- RBAC: a principal carries a role and the permissions it maps to. Services
  call `principal.require(...)`; role changes and invitations are rank-checked
  so a caller can never escalate a user above their own rank.
- The password path runs the hash verification even when the user does not
  exist, so a missing account and a wrong password cost the same and cannot be
  told apart by timing.

## Prompt injection and untrusted content

External website content is untrusted data and is never treated as an
instruction (Rule 9):

- `UntrustedContent` fences crawled copy with a per-render nonce and scans for
  injection patterns (instruction override, role reassignment, credential
  exfiltration, unauthorised execution, channel spoofing, fence escape).
- The agent context keeps SYSTEM, DEVELOPER_POLICY, USER, TOOL_OUTPUT and
  EXTERNAL_CONTENT in separate channels that are never concatenated.
- Crawled text is persisted by reference; the platform's own tables never hold a
  full untrusted page. An injection attempt becomes a security finding on the
  run, surfaced to the operator, and the copy is handled strictly as data.

## No fabrication

- Metrics carry provenance; an unmeasurable figure stays `null` with
  `provenance=unknown` and is never replaced by an estimate (Rules 1, 2, 14).
- Development-mode integration adapters label every value they produce as
  synthetic demonstration data, at the adapter, the stored row and the API.
- The deterministic model provider refuses rather than inventing prose.

## Chain-of-thought

The platform exposes observations, evidence, conclusions, recommendations,
confidence and limitations. It never exposes hidden model reasoning (Rule 8).
The result validator scans user-facing fields and fails any result that leaks
deliberation, and agent messages persist the observable channels only — private
reasoning is never written down.

## Policy and approval

Every consequential action passes through policy evaluation (Rule 5) and is
auditable (Rule 6). No action executes without the approval its risk and the
brand's risk category require; the execution agent refuses to run an unapproved
action and reports the block rather than working around it. Health, medical,
financial and other regulated categories raise the approval bar automatically.

## Secrets

- No secret is committed. `.env.example` is a template; populated `.env` files
  are git-ignored and Docker-ignored.
- API credentials and OAuth refresh tokens are never stored in normal columns;
  they go through the credential store, encrypted with a Fernet key supplied by
  configuration, behind a `secret_provider` interface that a KMS or vault
  implements later without touching call sites.
- Credential material and raw provider payloads have no API serializer and
  therefore cannot be returned by any endpoint.

## Audit

Every consequential action writes an audit record: actor, action, resource,
before/after state where relevant, the request id and the correlation id. Events
are emitted for the full agent and mission lifecycle. The `/api/v1/audit` and
`/api/v1/events` endpoints expose these to permitted roles.

## The security test suite

`tests/security/` and the isolation tests assert, against the real database, the
cases the Build Specification names: cross-tenant access, privilege escalation,
agent capability bypass, credential leakage, approval bypass, webhook spoofing,
prompt injection, malicious HTML and malicious structured data. These run in the
standard suite and in the quality gate (`make gate`).

## Reporting a vulnerability

This is a reference build. In a real deployment, route disclosures to a
monitored security address and do not file them as public issues.
