# Architectural Decision Log

## ADR-001 — Modular monolith with ports and adapters

**Date:** 2026-08-27  
**Decision:** Keep domain logic in one deployable Python system while separating repository and provider contracts from adapters.  
**Context:** The specifications require strong domain boundaries without premature microservices.  
**Alternatives considered:** independent services; route-centric implementation.  
**Reason:** A modular monolith minimizes operational complexity and keeps domain logic out of HTTP routes.  
**Consequences:** Modules can later be extracted; internal contracts require discipline.

## ADR-002 — Tenant context at every repository operation

**Date:** 2026-08-27  
**Decision:** Tenant-owned reads and writes require an explicit `TenantContext`; identifiers alone never authorize access.  
**Context:** Application filters that callers can omit are a common isolation failure.  
**Alternatives considered:** implicit global/request context; filtering only in API routes.  
**Reason:** Explicit context makes isolation testable below transport boundaries.  
**Consequences:** More verbose service calls; PostgreSQL RLS will later provide defense in depth.

## ADR-003 — Explicit external-content trust type

**Date:** 2026-08-27  
**Decision:** Crawled/tool content is wrapped with `UNTRUSTED_EXTERNAL_CONTENT` classification and rendered to models as delimited data.  
**Context:** External pages may contain prompt injection.  
**Alternatives considered:** string sanitization; prompt-only warnings.  
**Reason:** Provenance must survive transformations; sanitization cannot identify every instruction-shaped payload.  
**Consequences:** Agent/tool schemas must retain this metadata and policy resolvers must prevent elevation.
