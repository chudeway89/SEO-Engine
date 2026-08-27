# SEO Engine

SEO Engine is an evidence-first, policy-controlled, multi-tenant agentic SEO operating system.

## Current implementation

The repository is in Sprint 0. It contains the authoritative product specifications, persistent
implementation records, and the first tested modular-monolith primitives for tenancy, core domains,
task dependencies, evidence, authentication, external-content provenance, and SSRF protection.
Sprint exit gates are intentionally not claimed until the complete infrastructure and end-to-end
journeys pass.

## Development

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run ruff check .
uv run pytest
```

See [`docs/implementation/BUILD_STATUS.md`](docs/implementation/BUILD_STATUS.md) for the live ledger
and [`docs/implementation/IMPLEMENTATION_PLAN.md`](docs/implementation/IMPLEMENTATION_PLAN.md) for
the dependency-ordered Sprint 0/Sprint 1 plan.
