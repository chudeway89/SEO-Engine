# Integrations

Every external data source sits behind an adapter interface (Rule 8 of the
architecture rules: every integration has an adapter). For each provider there
are two adapters:

- a **production** adapter that talks to the real API; and
- a clearly-labelled **development** adapter that returns deterministic,
  synthetic data for working offline.

Which one is used is decided by whether credentials are configured, surfaced as
an `IntegrationMode` on the connection. The development adapter exists so the
architecture can be exercised end to end without credentials — it never exists
to fake real data (Rule 1).

## The honesty guarantee

The development adapter labels everything it produces as synthetic, at three
levels:

1. the adapter response carries `mode=development_adapter` and a notice;
2. every stored row has `provenance=synthetic_demo`, `is_synthetic=true` and a
   `data_label` of `SYNTHETIC DEMO DATA`;
3. the API echoes the mode and a notice on the connection and the sync result.

So a dashboard built on a development connection can still show numbers — it
just can never present them as real. A metric that no connected provider can
supply is returned as `null` with `provenance=unknown`, never an estimate
(Rule 14).

## Google Search Console (ANA-001, keyword demand)

- **Production:** OAuth2 (offline access, so a refresh token exists), the
  Search Analytics and Sitemaps APIs. Request construction, auth headers, error
  mapping and normalisation are all exercised in tests against an in-process
  fake Google served over httpx.
- A `401` maps to a non-retryable `CredentialError`, never a transient retry.
- Measured queries feed keyword research (so demand is observed, not assumed)
  and opportunity detection (recoverable positions).

## Google Analytics 4 (ANA-002, the lead baseline)

- **Production:** OAuth2, the Data API `runReport`, the Admin API for property
  discovery.
- Establishes the organic qualified-lead baseline the mission measures against.
  If no organic conversion events exist, the baseline is `null` and the mission
  runs without one rather than against a guess.

## CMS (EXE-001, execution)

- **Production:** a generic CMS adapter interface; concrete CMS connectors plug
  in behind it.
- **Draft-first:** creating a draft never publishes as a side effect. Publishing
  and every live-site edit require human approval through the policy engine.

## Connecting a provider

```
POST /api/v1/brands/{brand_id}/integrations   { "provider": "google_search_console" }
```

With no credentials configured this succeeds in `development_adapter` mode and
the response says so. With OAuth configured it begins the real authorisation
flow. Sync on demand:

```
POST /api/v1/brands/{brand_id}/integrations/{provider}/sync?days=28
```

Raw provider payloads are stored separately from the normalised rows, and the
raw payload is retained with its mode — so a normalised row can always be traced
back to exactly what the provider returned.

## Adding a provider

1. Define the adapter interface methods your engines need.
2. Implement the production adapter against the real API, with explicit error
   mapping (auth failures are non-retryable).
3. Implement the development adapter returning deterministic synthetic data,
   labelled at every level above.
4. Register the provider and its capabilities; the connection's `IntegrationMode`
   selects the adapter automatically.
5. Store credentials through the credential store, never in a normal column.

## Third-party SEO data (Ahrefs, Semrush)

Keys are configuration (`AHREFS_API_KEY`, `SEMRUSH_API_KEY`). Where no key is
present, the dependent metrics are simply absent with honest provenance — the
platform never substitutes an estimated search volume, difficulty or ranking
for a figure it cannot measure.
