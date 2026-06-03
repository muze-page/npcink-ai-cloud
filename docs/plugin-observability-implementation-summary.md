# Plugin Observability Implementation Summary

Status: implemented

Date: 2026-06-02

This note summarizes the current Cloud-side implementation so future agents can
continue without rediscovering the monitoring boundaries, entry points, and
verification commands.

## What Shipped

Plugin observability now has a practical v1 read model for:

- cross-site Cloud admin monitoring
- site-scoped Portal monitoring for end users
- hourly event and error trend charts
- plugin comparison charts
- site health tables
- error-code ranking and recent metadata-only errors
- health score and bounded attention items
- acknowledgement, mute, resolve, and clear-state workflow for attention items
- daily or weekly digest text derived from the same metadata summary

The Cloud monitoring surface remains read-only. It does not create a second
ability registry, second approval plane, second router, or WordPress write
owner.

## Key Contracts

- `docs/plugin-observability-v1.md` defines the metadata-only event contract,
  forbidden data, read model, health states, and attention item shape.
- `docs/plugin-observability-event-catalog.md` defines the current event
  families, error codes, and attention codes.
- `docs/plugin-observability-emitter-examples.md` gives concrete emitter
  examples for Abilities, Core, Adapter, and Cloud Addon.
- `docs/plugin-observability-e2e-acceptance.md` gives the real WordPress to
  Cloud acceptance checklist for Cloud Addon plus Abilities, Core, and Adapter.
- `docs/plugin-observability-plugin-side-handoff.md` gives copy-ready prompts
  for the plugin-side AI sessions that need to finish real trigger coverage.
- `docs/plugin-observability-dedupe-smoke-2026-06-03.md` records the real Cloud
  Addon flush evidence and the stable `event_id` dedupe rule that ignores
  timestamp drift when `event_id` is present.

Any new emitter event should be added to the event catalog before a plugin
starts sending it.

## Backend Entry Points

- `app/domain/observability/plugin_events.py`
  - Ingests plugin events.
  - Deduplicates events.
  - Builds portal and admin summaries.
  - Adds hourly `timeline` buckets.
  - Adds top-level `health` and `attention`.
  - Adds top-level `attention_workflow` and `digest`.
  - Adds per-site `health` in admin summaries.
  - Stores operator workflow state in
    `plugin_observability_attention_states`.

- `app/api/routes/service.py`
  - Admin-facing summary route:
    `GET /admin/plugin-observability`
  - Supports `window_hours`, `site_id`, and `plugin_slug` filters.

- `app/api/routes/portal.py`
  - Portal-facing site route:
    `GET /portal/v1/sites/{site_id}/plugin-observability`
  - Requires portal site access.
  - Returns only the authorized site's metadata summary.

## Frontend Entry Points

- `frontend/src/app/admin/plugin-observability/page.tsx`
  - Admin dashboard.
  - Shows health score, attention queue, event trend, plugin comparison, plugin
    breakdown, site health table, error-code ranking, and recent errors.
  - Lets operators filter watch items and mark them acknowledged, muted,
    resolved, or active again.

- `frontend/src/app/portal/monitoring/page.tsx`
  - Dedicated Portal monitoring page for a selected site.

- `frontend/src/components/portal/PortalPluginMonitoringPanel.tsx`
  - Reusable Portal panel used on the Portal workspace and the dedicated
    monitoring page.
  - Shows only site-scoped data.

- `frontend/src/lib/portal-client.ts`
  - Portal TypeScript types and API client method for plugin observability.

## Health and Attention Rules

Current health inputs:

- event count
- error count and error rate
- average latency
- last received event timestamp
- expected plugin reporting coverage
- ability catalog churn
- top error pressure

Current attention codes:

- `plugin_observability.inactive`
- `plugin_observability.error_rate_high`
- `plugin_observability.error_rate_elevated`
- `plugin_observability.plugin_error`
- `plugin_observability.plugin_missing`
- `plugin_observability.reporting_stale`
- `plugin_observability.latency_high`
- `plugin_observability.catalog_churn`
- `plugin_observability.top_error`

Attention items are capped so the dashboard stays usable. They are diagnostic
signals, not control-plane decisions.

## Demo Data

Use the local seed helper to create demo data for visual smoke tests:

```bash
uv run python -m app.dev.seed_plugin_observability_demo --scenario warning
uv run python -m app.dev.seed_plugin_observability_demo --scenario error
```

Add `--init-schema` only for disposable local SQLite fixtures. Do not use it as
a substitute for migrations in shared environments.

## Verification

Run the focused backend checks:

```bash
uv run --extra dev ruff check app/domain/observability/plugin_events.py tests/api/test_plugin_observability_admin.py tests/api/test_plugin_observability_portal.py
uv run --extra dev pytest tests/api/test_plugin_observability_admin.py tests/api/test_plugin_observability_portal.py
```

Run the frontend checks:

```bash
pnpm --dir frontend run lint
pnpm --dir frontend run type-check
```

Run the whitespace check:

```bash
git diff --check
```

For local visual smoke testing, use:

```bash
http://127.0.0.1:8010/admin/dev-entry?redirect=%2Fadmin%2Fplugin-observability
http://127.0.0.1:8010/portal/dev-entry?redirect=%2Fportal%2Fmonitoring
```

## Guardrails For Future Agents

- Do not expose `payload_json` in summary responses.
- Do not add prompt text, generated content, raw request bodies, raw responses,
  auth headers, API keys, tokens, cookies, signatures, or secrets to events.
- Do not make Cloud mutate local plugin configuration from this monitoring
  surface.
- Do not make Portal show cross-site admin data.
- Keep registration-class events sparse. Emit only when the ability catalog
  changes, a plugin activates, a plugin version changes, or a manual refresh is
  requested.
- Prefer new stable `event_kind`, `error_code`, or `attention` entries over
  ad-hoc display-only strings when adding high-value signals.

## Recommended Next Layer

The next high-value layer is alerting and operator workflow:

- persist alert acknowledgements and mute windows
- allow filtering attention by site, plugin, severity, and code
- add daily/weekly digest generation for site owners
- add a small synthetic-monitoring fixture for seeded demo data
- document emitter examples for `magick-ai-abilities`, `magick-ai-core`, and
  `magick-ai-adapter`

## AI Handoff Checklist

When another AI continues this work, start in this order:

1. Read `docs/plugin-observability-v1.md`.
2. Read `docs/plugin-observability-event-catalog.md`.
3. Read this implementation summary.
4. Inspect `PluginObservabilityService.get_summary()` and
   `PluginObservabilityService.get_admin_summary()` before changing response
   shape.
5. Read `docs/plugin-observability-dedupe-smoke-2026-06-03.md` before changing
   ingestion dedupe logic or plugin-side `event_id` generation.
6. Run the focused backend and frontend verification commands listed above.
7. Use the local Portal and Admin smoke-test URLs before claiming the monitoring
   UI is visible.
8. Use `docs/plugin-observability-emitter-examples.md` before asking plugin-side
   agents to add or adjust emitters.
9. Use `docs/plugin-observability-e2e-acceptance.md` before claiming real
   plugin-side monitoring is complete.
10. Use `docs/plugin-observability-plugin-side-handoff.md` when delegating
   Abilities, Core, Adapter, or Cloud Addon follow-up work to another AI
   session.

Do not start by adding new charts. First confirm whether the signal is already
represented as an event kind, error code, health reason, or attention code. If
the signal is new, extend the catalog and tests before changing the UI.
