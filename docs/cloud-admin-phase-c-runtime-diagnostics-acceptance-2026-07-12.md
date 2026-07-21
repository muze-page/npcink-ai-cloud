# Cloud Admin Phase C — Runtime Diagnostics Acceptance

Date: 2026-07-12
Surface: `/admin/troubleshooting`

## Change envelope

- Focused module: canonical runtime diagnostics index.
- Intended change: replace the static evidence-card catalog with a telemetry-driven health conclusion, anomaly queue, contextual inspector, and narrow evidence lanes.
- Explicit non-goals: no new alerting backend, no provider mutation, no routing changes, no ability/workflow/prompt truth, and no WordPress writes.
- Public contracts touched: URL query state only (`window` and `focus`). The existing `/api/admin/runtime-telemetry` response remains the evidence source.
- Rollback: revert the page, translations, contract updates, and dedicated E2E specification.

## Accepted operator model

1. Select a 24-hour, 72-hour, or 7-day diagnostic window.
2. Read the runtime health conclusion and four core metrics.
3. Select an active telemetry anomaly from the queue.
4. Inspect its evidence code, affected capability scope, and localized next diagnostic step.
5. Open the matching read-only evidence surface or advanced runtime metadata.

The previous one-group filter, static first-entry focus, and permanent evidence-card grid have been removed.

## Boundary acceptance

- Runtime telemetry remains Cloud-owned read-only operational evidence.
- Provider/model identifiers remain evidence detail rather than primary navigation.
- The page does not mutate suppliers, model routes, plugin abilities, prompts, approval state, billing, or WordPress content.
- Plugin, media, vector, and Agent feedback pages remain narrow diagnostic children rather than new top-level products.

## State acceptance

- Initial load preserves the page shell with a section skeleton.
- Refresh deduplicates requests and retains the last successful snapshot on failure.
- Empty telemetry produces an explicit healthy/no-anomaly state.
- URL state preserves the time window and focused anomaly across reload.
- Advanced runtime metadata is collapsed by default.

## Browser acceptance

- Desktop 1280 px: anomaly queue and 22 rem inspector render side by side without horizontal overflow.
- Mobile 390 × 844: the document width remains 390 px; anomaly rows stack and the default view contains no form inputs.
- Light and dark themes passed visual inspection; the original theme was restored.
- Common backend alert codes are rendered with localized operator-facing titles, explanations, severity labels, and next steps while retaining the raw evidence code.
- No live mutation was performed.

## Automated gates

- `pnpm --dir frontend type-check`
- `pnpm --dir frontend lint -- src/app/admin/troubleshooting/page.tsx`
- `pnpm --dir frontend test:contracts` — all frontend contracts passed; i18n completeness covered 1890 keys.
- `pnpm --dir frontend exec playwright test -c playwright.config.ts tests/e2e/admin-runtime-diagnostics-v2.spec.ts` — 2 passed.
- `pnpm run check:fast` — 70 contract tests passed, 1 skipped; 192 domain tests passed, 3 skipped.

## Follow-up

Continue Phase C with the diagnostic child pages. Start with the highest-volume surface, `/admin/plugin-observability`, and apply the shared diagnostic order: scope, conclusion, core metrics, trend, anomaly queue, inspector, and advanced evidence.
