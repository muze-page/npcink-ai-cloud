# Cloud Admin Phase C — Media Observability Acceptance

Date: 2026-07-12
Surface: `/admin/media-observability`

## Change envelope

- Focused module: cross-site media derivative runtime observability.
- Intended change: preserve the existing read-only media telemetry and charts while replacing the metric-card hero and exposed workflow metadata with a scoped diagnostic workspace and failure queue.
- Explicit non-goals: no image payload display, artifact mutation, WordPress write, local approval, prompt, router, or provider change.
- Public contracts touched: URL query state only (`window`, `format`, `site`, and `focus`). The existing GET endpoint remains unchanged.
- Rollback: revert the page, translations, dedicated E2E specification, and this acceptance record.

## Accepted operator model

1. Select the time window, target format, and optional site scope.
2. Read the compact job, success, P95, size-change, and failure summary.
3. Use trends and format/site evidence to identify abnormal scope.
4. Select a failed media job from the queue.
5. Inspect run, site, format, source-size, queue-wait, and processing evidence in the adjacent inspector.
6. Open advanced evidence only when workflow metadata or aggregate error codes are needed.

## Functional corrections

- The page now exits initial loading after an eight-second request timeout and offers a scoped retry.
- Request deduplication and sequence guards prevent stale responses from replacing the current URL scope.
- Refresh failure retains the last successfully loaded snapshot.
- Empty failure state renders once instead of duplicating queue and inspector placeholders.
- Chart panels explicitly contain responsive canvases, preventing page-level horizontal overflow after a desktop-to-mobile resize.
- Backend English health/error detail is not rendered as default operator copy.

## Boundary acceptance

- The surface remains read-only and metadata-only.
- Image payloads and temporary artifact contents remain excluded.
- Workflow metadata is secondary evidence behind a collapsed disclosure.
- No local WordPress approval, ability, workflow, routing, prompt, or content truth is created in Cloud.

## Browser and automated acceptance

- Desktop, 390 × 844 mobile, and dark-theme layouts passed real-browser inspection; the original light theme and desktop viewport were restored.
- Mobile document width remains 390 px without page-level horizontal overflow under a populated failure fixture.
- URL-backed window, format, site, and selected-run state is covered.
- Initial API failure and stale-snapshot refresh behavior are covered.
- `node tests/unit/admin-media-observability-i18n-contract.mjs` passed.
- Targeted ESLint for the page and E2E specification passed.
- Dedicated E2E against the running local frontend: 2 passed.
- The isolated Playwright build gate is temporarily blocked by duplicate `loadPaymentOrders` and `handleCancelPaymentOrder` definitions in the concurrently edited Portal billing page; this is outside the media module.

## Follow-up

Apply the same scoped diagnostic model to vector observability, then Agent feedback quality. After those surfaces converge, extract only the repeated diagnostic scope, summary, queue, and inspector primitives into shared components.
