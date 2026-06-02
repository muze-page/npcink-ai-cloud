# Plugin Observability E2E Acceptance

Status: acceptance checklist

Date: 2026-06-02

Use this checklist before claiming that plugin observability is ready for
internal alpha. It verifies the real chain from WordPress emitters, through
`magick-ai-cloud-addon`, into Cloud Admin and Portal read surfaces.

## Boundary

Plugin observability is metadata-only.

Cloud may store and display event counts, status, latency, stable error codes,
site ids, plugin slugs, event kinds, and bounded attention summaries.

Cloud must not store or display prompts, generated content, raw ability
definitions, raw callback payloads, raw HTTP bodies, API keys, cookies, nonces,
authorization headers, signatures, tokens, or WordPress content bodies.

The WordPress plugins remain the local truth for abilities, governance,
approval, OpenClaw projection, routing decisions, and WordPress writes. Cloud is
only an observability read surface and operator workflow detail.

## Required Components

WordPress side:

- `magick-ai-cloud-addon`
- `magick-ai-abilities`
- `magick-ai-core`
- `magick-ai-adapter`

Cloud side:

- API, frontend, proxy, Postgres, Redis, and workers running.
- Latest Alembic migration applied.
- A provisioned active site and active Cloud API key.
- Cloud Addon installed, verified, and monitoring enabled.

Local Cloud smoke URLs:

```text
http://127.0.0.1:8010/admin/dev-entry?redirect=%2Fadmin%2Fplugin-observability
http://127.0.0.1:8010/portal/dev-entry?redirect=%2Fportal%2Fmonitoring
```

## Cloud Setup Check

Run from `/Users/muze/gitee/magick-ai-cloud`:

```bash
docker compose -f docker-compose.dev.yml ps
docker compose -f docker-compose.dev.yml exec -T api alembic upgrade head
docker compose -f docker-compose.dev.yml exec -T api python -c "from PIL import Image; import app.api.main; print('ok')"
```

Expected:

- `api`, `frontend`, `proxy`, `postgres`, `redis`, and workers are running.
- Migration reaches `head`.
- Import check prints `ok`.

If the local UI needs demo data before WordPress is wired, seed metadata-only
fixtures:

```bash
docker compose -f docker-compose.dev.yml exec -T api python -m app.dev.seed_plugin_observability_demo
```

Do not use demo data as proof of real plugin emitter coverage.

## WordPress Addon Gate

Verify these states first:

1. Cloud Addon is installed and connected to the expected Cloud base URL.
2. Cloud API key verifies successfully.
3. Monitoring is enabled.
4. The WordPress site id shown by the addon matches the Portal site selector.

Expected when the addon is absent, unverified, or monitoring is disabled:

- No plugin events are uploaded.
- Portal may show an empty monitoring state.
- Admin may show no events for that site.

## Emitter Trigger Checklist

### magick-ai-abilities

Trigger:

- Activate the plugin.
- Run the manual ability catalog refresh if available.
- Change the ability catalog in a way that changes the catalog hash.
- Execute one ability callback successfully.
- Execute or simulate one ability callback failure.

Expected event families:

- `abilities.catalog.changed`
- `abilities.callback.completed`
- `abilities.callback.failed`

Expected Cloud evidence:

- Admin plugin breakdown includes `magick-ai-abilities`.
- Portal site view includes `magick-ai-abilities`.
- Success callbacks increase event totals and success rate inputs.
- Failed callbacks create a stable error code and a recent metadata-only error.

Registration-class acceptance:

- Repeated page refreshes must not upload one registration event per ability.
- Repeating the same catalog hash should not create a new registration burst.
- A catalog hash change, plugin activation, plugin version change, or manual
  refresh may create a sparse registration-class event.

### magick-ai-core

Trigger:

- Run a preflight that completes.
- Run or simulate a preflight that is blocked.
- Create, approve, and reject proposals where the local workflow supports it.
- Confirm audit metadata is emitted without raw proposal payloads.

Expected event families:

- `core.preflight.completed`
- `core.preflight.blocked`
- `core.proposal.create`
- `core.proposal.approve`
- `core.proposal.reject`

Expected Cloud evidence:

- Admin plugin breakdown includes `magick-ai-core`.
- Portal site view includes `magick-ai-core`.
- Blocked or failed states appear as warning/error metadata, not as local
  approval controls.
- Cloud does not expose raw proposal payloads or mutate local approval state.

### magick-ai-adapter

Trigger:

- Dispatch one OpenClaw adapter request successfully.
- Dispatch or simulate one adapter failure.
- Trigger one Core API request path from the adapter.

Expected event families:

- `adapter.openclaw.dispatch.completed`
- `adapter.openclaw.dispatch.failed`
- `adapter.core.request`
- `adapter.proposal.create`

Expected Cloud evidence:

- Admin plugin breakdown includes `magick-ai-adapter`.
- Portal site view includes `magick-ai-adapter`.
- Adapter failures influence health, attention, error ranking, and recent
  errors.
- Cloud does not expose raw OpenClaw requests, raw responses, or WordPress write
  payloads.

### magick-ai-cloud-addon

Trigger:

- Verify connection.
- Upload a batch that contains accepted events.
- Temporarily make Cloud unavailable, then restore it and flush the local
  buffer if the addon supports buffering.

Expected event families:

- `addon.batch.uploaded`
- optional bounded upload failure/retry metadata

Expected Cloud evidence:

- Addon upload telemetry stays sparse.
- Upload success/failure is metadata-only.
- Addon does not become a second plugin registry or local control plane.

## Cloud Read-Surface Acceptance

Admin:

- Open `/admin/plugin-observability`.
- Confirm cross-site totals appear.
- Confirm Digest appears.
- Confirm Attention items appear when errors, stale reporting, missing plugins,
  or latency pressure exist.
- Confirm charts render for hourly event/error trend and plugin error pressure.
- Confirm plugin table, site table, error code ranking, and recent errors are
  visible.
- Confirm filters work for `window_hours`, plugin, site id, severity, status,
  and error code.
- Confirm Ack, Mute 24h, Resolve, and Clear only update Cloud operator workflow
  state.

Portal:

- Open `/portal/monitoring`.
- Confirm only the selected authorized site appears.
- Confirm site totals, health, Digest, trend chart, plugin comparison, plugin
  cards, and recent errors are visible.
- Confirm cross-site admin data is not visible.
- Confirm no attention workflow mutation controls are exposed to the portal
  user.

## API Acceptance

Admin summary:

```bash
curl -sS "http://127.0.0.1:8010/api/admin/plugin-observability?window_hours=24"
```

Portal summary:

```bash
curl -sS "http://127.0.0.1:8010/api/portal/sites/site_magick_ai_local/plugin-observability?window_hours=24"
```

Expected response shape:

- `totals`
- `plugins`
- `timeline`
- `health`
- `attention`
- `attention_workflow`
- `digest`
- `errors`
- `recent_errors`

Admin may also include `sites`.

Rejected response shape:

- No `payload_json`.
- No raw request or response body.
- No prompt, generated content, secret, token, cookie, nonce, or auth header.

## Deduplication and Rate-Limit Acceptance

Run this after the WordPress emitters are wired:

1. Record current admin event totals for the site and plugin.
2. Refresh the WordPress admin page five times without changing the ability
   catalog.
3. Refresh the Cloud Portal monitoring page.
4. Record event totals again.

Expected:

- Registration-class totals do not grow by one event per ability per request.
- Same catalog hash does not create a burst.
- Callback, preflight, adapter dispatch, and addon upload events may grow only
  when the corresponding real action occurred.

Then force a catalog hash change or manual refresh.

Expected:

- A sparse `abilities.catalog.changed` event appears.
- Health does not degrade from registration noise alone.

## Visual Evidence

Use Playwright or the in-app browser after real events have arrived.

Recommended local screenshots:

```bash
pnpm --dir frontend exec playwright screenshot \
  "http://127.0.0.1:8010/admin/dev-entry?redirect=%2Fadmin%2Fplugin-observability" \
  /tmp/magick-admin-plugin-observability.png

pnpm --dir frontend exec playwright screenshot \
  "http://127.0.0.1:8010/portal/dev-entry?redirect=%2Fportal%2Fmonitoring" \
  /tmp/magick-portal-monitoring.png
```

If the Next dev server restarts during parallel screenshots, run screenshots
sequentially and wait for stable page text such as `DIGEST`, `ATTENTION`, and
`Recent errors`.

## Focused Verification Commands

Cloud backend:

```bash
uv run --extra dev ruff check app/core/models.py app/domain/observability/plugin_events.py app/api/routes/service.py app/dev/seed_plugin_observability_demo.py tests/api/test_plugin_observability_admin.py tests/api/test_plugin_observability_portal.py migrations/versions/20260602_0035_plugin_observability_attention_states.py
uv run --extra dev pytest tests/api/test_plugin_observability_admin.py tests/api/test_plugin_observability_portal.py
```

Cloud frontend:

```bash
pnpm --dir frontend run type-check
pnpm --dir frontend run lint
git diff --check
```

## Troubleshooting

No data in Portal:

- Confirm the selected Portal site id matches the Cloud Addon site id.
- Confirm the addon is verified and monitoring is enabled.
- Confirm events reached `POST /v1/observability/plugin-events`.
- Confirm the Portal user has access to that site.

Admin has data but Portal is empty:

- Check the `site_id` filter.
- Confirm the Portal session selected the same site.
- Confirm the admin data is not demo data for a different site.

Registration events flood the dashboard:

- Check the emitter only sends registration-class events on activation, manual
  refresh, plugin version change, or catalog hash change.
- Check the addon de-duplicates same catalog hash emissions.

Cloud receives events but UI is empty:

- Check the API summary response includes `totals.events_total > 0`.
- Check frontend logs for runtime errors.
- Re-run type-check and lint.

API import fails with `ModuleNotFoundError: No module named 'PIL'`:

- Rebuild the API and worker images.
- Verify the runtime image includes `Pillow`.

```bash
docker compose -f docker-compose.dev.yml build api worker callback-worker ops-worker
docker compose -f docker-compose.dev.yml up -d api worker callback-worker ops-worker proxy frontend
docker compose -f docker-compose.dev.yml exec -T api python -c "from PIL import Image; import app.api.main; print('ok')"
```

OTel exporter reports local collector errors:

- Treat this as local telemetry noise unless tests fail or the API cannot serve
  requests.
- Do not confuse OTel export retries with plugin observability ingestion
  failure.

