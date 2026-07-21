# Cloud Admin Phase C — Plugin Observability Acceptance

Date: 2026-07-12
Surface: `/admin/plugin-observability`

## Change envelope

- Focused module: cross-site plugin runtime observability.
- Intended change: keep the existing telemetry, charts, site evidence, and Cloud display-state workflow while replacing the metric-card hero and inline multi-action cards with a scoped diagnostic workspace.
- Explicit non-goals: no plugin setting changes, no local approval or ability mutation, no routing change, and no WordPress write.
- Public contracts touched: URL query state only (`window`, `plugin`, `site`, and `focus`). Existing GET data and POST attention-state endpoints remain unchanged.
- Rollback: revert the page, translations, dedicated E2E specification, and this acceptance record.

## Accepted operator model

1. Select the time window, plugin source, and optional site scope.
2. Read the compact event, success, latency, active-site, and open-watch summary.
3. Read the localized digest and health conclusion.
4. Select a watch item from the queue.
5. Review its site, plugin, error code, and suggested step in the adjacent inspector.
6. Apply acknowledge, mute, or resolve only from the inspector.
7. Continue to trends, plugin/site evidence, and error detail when event volume exists.

## Functional corrections

- A watch item is no longer hidden when the selected window has zero event volume.
- Zero event volume with an active watch item shows the queue and inspector but suppresses empty charts and evidence tables.
- Request deduplication and sequence guards prevent stale responses from replacing current scope.
- Refresh failure retains the last successful snapshot.
- Attention-state success uses a Toast instead of creating a layout-shifting success card.

## Boundary acceptance

- Attention state remains Cloud display state only.
- The page does not mutate local plugin settings, approval state, ability definitions, routing, prompts, or WordPress content.
- Raw payloads and requests remain excluded from the default view.

## Browser and automated acceptance

- Desktop and 390 × 844 queue/inspector flows passed real-browser inspection and the dedicated E2E fixture.
- Mobile document width remains 390 px without page-level horizontal overflow.
- Light and dark themes passed visual inspection; the original theme was restored.
- URL-backed window, plugin, site, and focus state survives navigation and reload.
- Attention-state POST and transient Toast feedback are covered without changing production data.
- `pnpm --dir frontend type-check` passed.
- `pnpm --dir frontend lint -- src/app/admin/plugin-observability/page.tsx` passed.
- `pnpm --dir frontend test:contracts` passed; i18n completeness covered 1890 keys.
- `pnpm --dir frontend exec playwright test -c playwright.config.ts tests/e2e/admin-plugin-observability-v2.spec.ts` — 3 passed.
- `pnpm run check:fast` — 70 contract tests passed, 1 skipped; 192 domain tests passed, 3 skipped.

## Follow-up

Continue the shared diagnostic model with media and vector observability. Their default pages should preserve charts but move workflow metadata, identifiers, and raw failure evidence behind the anomaly inspector or advanced disclosure.
