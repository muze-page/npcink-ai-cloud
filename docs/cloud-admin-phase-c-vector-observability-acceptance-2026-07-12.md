# Cloud Admin Phase C — Vector Observability Acceptance

Date: 2026-07-12
Surface: `/admin/vector-observability`

## Change envelope

- Focused module: cross-site Site Knowledge indexing and semantic-search observability.
- Intended change: preserve read-only telemetry and charts while replacing the metric-card hero and equal-weight evidence cards with a scoped diagnostic workspace, error queue, and inspector.
- Explicit non-goals: no sync, reindex, repair, vector-store mutation, WordPress write, local approval, query-text display, or embedding display.
- Public contracts touched: URL query state only (`window`, `site`, and `focus`). The existing GET endpoint remains unchanged.
- Rollback: revert the page, translations, dedicated E2E specification, and this acceptance record.

## Accepted operator model

1. Select a time window and optional site scope.
2. Read indexed-document, search, no-hit, P95, and aggregate-error summaries.
3. Compare search/index trends, site coverage, and intent distribution.
4. Select an error code from the queue.
5. Inspect occurrence count, last-seen time, and current scope in the adjacent inspector.
6. Open advanced index snapshots only when provider, dimensions, backend, or captured coverage is needed.

## Functional corrections

- Filter and selected-error state is URL-backed and survives reload/navigation.
- Initial requests time out after eight seconds and expose a scoped retry instead of replacing the page with a generic error screen.
- Refresh failure retains the last successfully loaded snapshot.
- Request sequence guards prevent stale responses from replacing the current scope.
- Responsive chart containers prevent page-level horizontal overflow after viewport changes.
- Error evidence is presented as a queue and inspector rather than equal-weight cards.

## Boundary acceptance

- The surface remains read-only.
- Chunk text, embedding vectors, and raw query text remain excluded.
- No local Site Knowledge registry, workflow, approval, preflight, audit, or WordPress write truth is created in Cloud.
- Index snapshots remain secondary runtime evidence behind a collapsed disclosure.

## Browser and automated acceptance

- Desktop, 390 × 844 mobile, and dark-theme layouts passed real-browser inspection; the original light theme and desktop viewport were restored.
- Mobile document width remains 390 px under a populated error fixture.
- URL-backed window, site, and selected-error state is covered.
- Initial API failure and stale-snapshot refresh behavior are covered.
- `node tests/unit/admin-vector-observability-i18n-contract.mjs` passed.
- Targeted ESLint passed.
- Dedicated E2E against the running local frontend: 2 passed.

## Follow-up

Refactor Agent feedback quality as the final Phase C diagnostic surface, then extract the repeated scope, summary, queue, inspector, and stale-snapshot patterns into shared components without generalizing business-specific evidence.
