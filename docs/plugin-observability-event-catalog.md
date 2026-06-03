# Plugin Observability Event Catalog

Status: active reference

Date: 2026-06-02

This catalog defines the current event and error vocabulary for Magick AI
plugin observability. New events should be added here before emitters start
using them.

## Event Families

### Abilities

| Event kind | Status | Meaning | Primary fields |
| --- | --- | --- | --- |
| `abilities.catalog.changed` | `ok` | Stable ability catalog hash changed, plugin activated, plugin version changed, or manual refresh emitted a catalog snapshot. | `plugin_version`, `ability_count`, `catalog_hash`, `reason` |
| `abilities.callback.completed` | `ok` | Ability callback completed successfully. | `ability_id`, `latency_ms`, `correlation_id` |
| `abilities.callback.failed` | `error` | Ability callback failed or returned an error. | `ability_id`, `latency_ms`, `error_code` |

Do not emit per-ability registration events during ordinary boot. Catalog
registration is represented by `abilities.catalog.changed`.

### Core

| Event kind | Status | Meaning | Primary fields |
| --- | --- | --- | --- |
| `core.proposal.create` | `ok` or `error` | Proposal creation completed or failed. | `proposal_id`, `ability_id`, `latency_ms`, `error_code` |
| `core.proposal.plan_ingest` | `ok` or `error` | Read-only plan intake created proposal records or failed validation. | `ability_id`, `proposal_count`, `blocked_count`, `latency_ms`, `error_code` |
| `core.proposal.approve` | `ok` or `error` | Proposal approval completed or failed. | `proposal_id`, `ability_id`, `latency_ms`, `error_code` |
| `core.proposal.reject` | `ok` or `error` | Proposal rejection completed or failed. | `proposal_id`, `ability_id`, `latency_ms`, `error_code` |
| `core.commit.preflight` | `ok`, `warning`, or `error` | Commit preflight completed, produced a governance block, or failed. | `proposal_id`, `ability_id`, `correlation_id`, `latency_ms`, `error_code` |

Core events must not expose prompt text, generated content, approval notes, or
raw proposal or policy payloads. Expected governance preflight blocks use
`status=warning` with the Core `magick_ai_core_*` error code; failed paths use
`status=error`.

### Adapter

| Event kind | Status | Meaning | Primary fields |
| --- | --- | --- | --- |
| `adapter.openclaw.dispatch.completed` | `ok` | OpenClaw channel dispatch completed. | `adapter_request_id`, `route`, `latency_ms`, `status_code` |
| `adapter.openclaw.dispatch.failed` | `error` | OpenClaw channel dispatch failed. | `adapter_request_id`, `route`, `latency_ms`, `status_code`, `error_code` |
| `adapter.core.request.completed` | `ok` | Adapter call to Core completed. | `route`, `latency_ms`, `status_code` |
| `adapter.core.request.failed` | `error` | Adapter call to Core failed. | `route`, `latency_ms`, `status_code`, `error_code` |

Adapter events may include redacted method and route names. They must not
include request bodies, response bodies, auth headers, or channel payloads.

### Cloud Addon

| Event kind | Status | Meaning | Primary fields |
| --- | --- | --- | --- |
| `addon.batch.uploaded` | `ok` | Addon uploaded a monitoring batch to Cloud. | `executed_count`, `failed_count`, `deduplicated` |
| `addon.batch.failed` | `error` | Addon could not upload monitoring data. | `failed_count`, `error_code` |
| `addon.monitoring.disabled` | `warning` | Monitoring is intentionally disabled. | `status_detail` |

Addon events should be sparse. Do not create noisy per-event upload telemetry
that floods the same monitoring surface it is meant to support.

## Error Codes

| Error code | Source | Meaning | Suggested action |
| --- | --- | --- | --- |
| `abilities.callback_timeout` | Abilities | Ability callback exceeded the local timeout. | Inspect the ability callback and recent latency trend. |
| `abilities.callback_error` | Abilities | Ability callback returned an error or threw. | Check the ability id and local plugin logs. |
| `magick_ai_core_proposal_not_approved` | Core | Commit preflight was requested before local approval. | Review the proposal in local WordPress Core. |
| `magick_ai_core_proposal_items_blocked` | Core | Commit preflight found missing input or blocked proposal items. | Review the proposal preview and required human input locally. |
| `magick_ai_core_commit_preflight_already_issued` | Core | Core already issued one execution handoff for the approved input. | Use the adapter's idempotent execution record or create a fresh proposal after review. |
| `core.audit_failed` | Core | Audit metadata could not be recorded. | Check local audit storage and retry path. |
| `adapter.dispatch_failed` | Adapter | OpenClaw dispatch failed. | Check adapter route, Core availability, and channel configuration. |
| `adapter.core_unavailable` | Adapter | Adapter could not reach Core. | Check Core plugin status and local REST/API bridge. |
| `addon.upload_failed` | Cloud Addon | Addon could not upload monitoring batch. | Verify Cloud API key, base URL, and network reachability. |
| `addon.auth_invalid` | Cloud Addon | Cloud rejected addon credentials. | Re-verify the Cloud API key in addon settings. |
| `observability.schema_invalid` | Cloud | Cloud rejected an invalid event shape. | Compare emitter fields with `plugin-observability-v1`. |

## Attention Codes

| Attention code | Severity | Trigger |
| --- | --- | --- |
| `plugin_observability.inactive` | `warning` | No plugin events in the selected window. |
| `plugin_observability.error_rate_high` | `error` | Error rate is at or above 5 percent. |
| `plugin_observability.error_rate_elevated` | `warning` | Error rate is above zero but below the high threshold. |
| `plugin_observability.plugin_error` | `warning` or `error` | A specific plugin has error events. |
| `plugin_observability.plugin_missing` | `warning` | One or more expected Magick AI plugins did not report in the selected window. |
| `plugin_observability.reporting_stale` | `warning` | Last event is stale for the selected window. |
| `plugin_observability.latency_high` | `warning` | Average latency is at or above 3000 ms. |
| `plugin_observability.catalog_churn` | `warning` | Ability catalog changed repeatedly in the selected window. |
| `plugin_observability.top_error` | `warning` | Highest ranked error code is present in the selected window. |

These attention codes are advisory. They do not authorize Cloud to mutate local
plugin state or bypass local approval.
