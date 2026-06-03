# Plugin Observability Emitter Examples

Status: reference

Date: 2026-06-02

Use these examples when implementing emitters in `magick-ai-abilities`,
`magick-ai-core`, `magick-ai-adapter`, or the Cloud Addon collector. Emitters
must follow `docs/plugin-observability-v1.md` and
`docs/plugin-observability-event-catalog.md`.

## Shared Shape

```json
{
  "schema_version": "2026-06-01",
  "plugin_slug": "magick-ai-abilities",
  "plugin_version": "0.1.0",
  "source": "local",
  "event_kind": "abilities.callback.completed",
  "event_id": "evt_...",
  "status": "ok",
  "latency_ms": 42,
  "captured_at": "2026-06-02T10:00:00Z",
  "emitted_at": "2026-06-02T10:00:00Z"
}
```

Do not include prompt text, generated content, raw callback payloads, raw
requests, raw responses, auth headers, keys, cookies, tokens, nonces, signatures,
or secrets.

## magick-ai-abilities

### Catalog Changed

Emit only when the ability catalog hash changes, the plugin activates, the
plugin version changes, or a manual refresh requests it.

```json
{
  "schema_version": "2026-06-01",
  "plugin_slug": "magick-ai-abilities",
  "plugin_version": "0.1.0",
  "source": "local",
  "event_kind": "abilities.catalog.changed",
  "event_id": "catalog_0.1.0_4f8c...",
  "status": "ok",
  "status_detail": "plugin_activation",
  "captured_at": "2026-06-02T10:00:00Z",
  "emitted_at": "2026-06-02T10:00:00Z"
}
```

### Callback Completed

```json
{
  "schema_version": "2026-06-01",
  "plugin_slug": "magick-ai-abilities",
  "plugin_version": "0.1.0",
  "source": "local",
  "event_kind": "abilities.callback.completed",
  "event_id": "ability_cb_...",
  "status": "ok",
  "ability_id": "magick-ai/create-draft",
  "correlation_id": "corr_...",
  "latency_ms": 85,
  "captured_at": "2026-06-02T10:00:00Z",
  "emitted_at": "2026-06-02T10:00:00Z"
}
```

### Callback Failed

```json
{
  "schema_version": "2026-06-01",
  "plugin_slug": "magick-ai-abilities",
  "plugin_version": "0.1.0",
  "source": "local",
  "event_kind": "abilities.callback.failed",
  "event_id": "ability_cb_...",
  "status": "error",
  "ability_id": "magick-ai/create-draft",
  "correlation_id": "corr_...",
  "latency_ms": 5000,
  "error_code": "abilities.callback_timeout",
  "status_detail": "timeout",
  "captured_at": "2026-06-02T10:00:00Z",
  "emitted_at": "2026-06-02T10:00:00Z"
}
```

## magick-ai-core

### Proposal Created

```json
{
  "schema_version": "2026-06-01",
  "plugin_slug": "magick-ai-core",
  "plugin_version": "0.1.0",
  "source": "local",
  "event_kind": "core.proposal.create",
  "status": "ok",
  "proposal_id": "proposal_...",
  "ability_id": "magick-ai/create-draft",
  "latency_ms": 34,
  "captured_at": "2026-06-02T10:00:00Z",
  "emitted_at": "2026-06-02T10:00:00Z"
}
```

### Commit Preflight Completed

```json
{
  "schema_version": "2026-06-01",
  "plugin_slug": "magick-ai-core",
  "plugin_version": "0.1.0",
  "source": "local",
  "event_kind": "core.commit.preflight",
  "status": "ok",
  "proposal_id": "proposal_...",
  "ability_id": "magick-ai/create-draft",
  "correlation_id": "corr_...",
  "latency_ms": 34,
  "captured_at": "2026-06-02T10:00:00Z",
  "emitted_at": "2026-06-02T10:00:00Z"
}
```

### Commit Preflight Blocked

```json
{
  "schema_version": "2026-06-01",
  "plugin_slug": "magick-ai-core",
  "plugin_version": "0.1.0",
  "source": "local",
  "event_kind": "core.commit.preflight",
  "status": "warning",
  "proposal_id": "proposal_...",
  "error_code": "magick_ai_core_proposal_not_approved",
  "captured_at": "2026-06-02T10:00:00Z",
  "emitted_at": "2026-06-02T10:00:00Z"
}
```

Core proposal approve/reject and plan ingest use the same metadata-only shape
with `event_kind` values `core.proposal.approve`, `core.proposal.reject`, and
`core.proposal.plan_ingest`. Do not include proposal input, preview, caller
payloads, approval notes, generated content, or policy payloads.

## magick-ai-adapter

### OpenClaw Dispatch Completed

```json
{
  "schema_version": "2026-06-01",
  "plugin_slug": "magick-ai-adapter",
  "plugin_version": "0.1.0",
  "source": "local",
  "event_kind": "adapter.openclaw.dispatch.completed",
  "event_id": "dispatch_...",
  "status": "ok",
  "adapter_request_id": "adapter_req_...",
  "method": "POST",
  "route": "/openclaw/execute",
  "status_code": 200,
  "latency_ms": 140,
  "captured_at": "2026-06-02T10:00:00Z",
  "emitted_at": "2026-06-02T10:00:00Z"
}
```

### OpenClaw Dispatch Failed

```json
{
  "schema_version": "2026-06-01",
  "plugin_slug": "magick-ai-adapter",
  "plugin_version": "0.1.0",
  "source": "local",
  "event_kind": "adapter.openclaw.dispatch.failed",
  "event_id": "dispatch_...",
  "status": "error",
  "adapter_request_id": "adapter_req_...",
  "method": "POST",
  "route": "/openclaw/execute",
  "status_code": 502,
  "latency_ms": 900,
  "error_code": "adapter.dispatch_failed",
  "status_detail": "core_unavailable",
  "captured_at": "2026-06-02T10:00:00Z",
  "emitted_at": "2026-06-02T10:00:00Z"
}
```

## Cloud Addon Collector

- Buffer events locally when Cloud is unavailable.
- Upload only after the Cloud Addon is installed, verified, and monitoring is
  enabled.
- Apply registration-class de-duplication before upload.
- Upload batches to `POST /v1/observability/plugin-events`.
- Keep addon upload telemetry sparse.

Example addon batch event:

```json
{
  "schema_version": "2026-06-01",
  "plugin_slug": "magick-ai-cloud-addon",
  "plugin_version": "0.1.0",
  "source": "local",
  "event_kind": "addon.batch.uploaded",
  "event_id": "addon_batch_...",
  "status": "ok",
  "executed_count": 12,
  "failed_count": 0,
  "deduplicated": true,
  "captured_at": "2026-06-02T10:00:00Z",
  "emitted_at": "2026-06-02T10:00:00Z"
}
```
