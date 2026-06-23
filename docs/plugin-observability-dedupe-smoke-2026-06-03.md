# Plugin Observability Dedupe Smoke 2026-06-03

Status: completed

Date: 2026-06-03

Scope: Cloud-side plugin observability ingestion, stable `event_id`
deduplication, and Portal/Admin read surfaces.

## Summary

The Cloud Addon was flushed against the local Cloud dev stack and the stored
event counts were checked from PostgreSQL. Stable `event_id` deduplication was
then tightened so timestamp drift no longer creates duplicate stored events
when the semantic event id is the same.

This remains a metadata-only monitoring path. Cloud receives and summarizes
events, but it does not mutate WordPress plugin state, own the ability catalog,
approve proposals, route execution, or write WordPress content.

## Real Flush Evidence

Local Cloud Addon buffer before flush:

- buffered events: `193`
- unique event ids in buffer: `175`
- duplicate event ids in buffer: `18`
- plugins represented: `magick-ai-abilities`, `magick-ai-core`,
  `magick-ai-adapter`

Flush result:

- Addon buffer: `193 -> 0`
- Cloud stored rows for the four flush batches: `175`
- skipped duplicates: `18`
- received batch timestamps:
  - `2026-06-03 02:55:34.509533+00`
  - `2026-06-03 02:55:34.545648+00`
  - `2026-06-03 02:55:34.56202+00`
  - `2026-06-03 02:55:34.576622+00`

The `193 sent -> 175 stored` result confirmed that stable `event_id`
deduplication was already suppressing many repeated buffered events.

## Gap Found

Two `core.proposal.plan_ingest` rows still duplicated by `event_id` because the
previous Cloud dedupe key included `emitted_at` and `captured_at`. The same
semantic event id could be stored twice when timestamps drifted by one second.

Observed duplicate shape:

- plugin: `magick-ai-core`
- event kind: `core.proposal.plan_ingest`
- same `event_id`
- different `emitted_at` / `captured_at`
- two distinct `dedupe_key` values

## Implemented Rule

Cloud deduplication now uses this rule:

- when `event_id` is present:
  - hash `site_id`, `key_id`, `plugin_slug`, `event_kind`, and `event_id`
- when `event_id` is absent:
  - fall back to `site_id`, `key_id`, `plugin_slug`, `event_kind`,
    `emitted_at`, `captured_at`, `correlation_id`, and `adapter_request_id`

This preserves stable semantic dedupe for plugin-side events while avoiding
over-aggregation for legacy or incomplete events that do not provide an
`event_id`.

## Runtime Smoke

A container-side smoke test was run against the active local Cloud API process.
The temporary test event was inserted using the real `PluginObservabilityService`
and then deleted.

Result:

```text
first_stored=1
first_duplicate=0
second_stored=0
second_duplicate=1
stored_rows_before_cleanup=1
```

Cleanup check:

```text
count(event_id='smoke_event_id_timestamp_drift_20260603') = 0
```

## Portal/Admin Read Surface Evidence

After the real flush, the local Portal page showed:

- URL: `http://127.0.0.1:8010/portal/monitoring`
- site: `site_npcink_local`
- events: `1,522`
- errors: `82`
- plugins: `3`
- last seen: `2026/6/3 10:55`

The local Admin page showed:

- URL: `http://127.0.0.1:8010/admin/plugin-observability`
- cross-site events: `1,589`
- cross-site errors: `83`
- sites: `2`
- plugins: `3`
- local site row: `site_npcink_local`, `1,522` events, `82` errors

Local screenshots were generated under `.tmp/observability-smoke/` during the
smoke run. They are validation artifacts and are not committed.

## Validation

Commands run:

```bash
uv run --extra dev pytest tests/api/test_observability_routes.py
uv run --extra dev pytest tests/api/test_observability_routes.py tests/api/test_plugin_observability_admin.py tests/api/test_plugin_observability_portal.py
uv run --extra dev ruff check app/domain/observability/plugin_events.py tests/api/test_observability_routes.py tests/api/test_plugin_observability_admin.py tests/api/test_plugin_observability_portal.py
```

Results:

- focused API tests: `5 passed`
- observability API/Admin/Portal tests: `17 passed`
- ruff: passed

The test process reported transient OpenTelemetry export `Bad Gateway`
messages after test completion. They did not fail the test run and were not
related to plugin observability ingestion.

## Follow-Up Guidance

Future plugin-side emitters should treat `event_id` as a stable semantic
operation id, not an upload attempt id. If an event reports the same operation
again with different collector timestamps, Cloud will now store only one row.

Registration-class events should remain sparse:

- emit on ability catalog hash change
- emit on plugin activation
- emit on explicit manual refresh
- emit on plugin version change

Do not reintroduce per-ability registration events on ordinary WordPress boot
or request handling.
