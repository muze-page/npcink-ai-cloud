# Plugin Observability v1

Status: active contract

Date: 2026-06-03

Scope: `magick-ai-abilities`, `magick-ai-core`, `magick-ai-adapter`,
`npcink-cloud-addon`, and the Cloud plugin observability read surfaces.

## Boundary

Plugin observability is a metadata-only monitoring contract. Local WordPress
plugins remain the source of truth for abilities, governance, approval,
OpenClaw projection, routing decisions, and WordPress writes. Cloud only
receives bounded metadata from `npcink-cloud-addon` after the addon is
installed, verified, and monitoring is enabled.

Cloud must not use this stream to create a second plugin registry, second
approval plane, second router truth, or second WordPress write owner.

## Transport

- WordPress plugins emit local events through `npcink_observability_event`.
- `npcink-cloud-addon` is the only WordPress-side uploader.
- If the addon is absent, unverified, or monitoring is disabled, events stay
  local and are not uploaded.
- Cloud receives batches at `POST /v1/observability/plugin-events`.
- Portal reads only the current site administrator's authorized site.
- Admin reads may aggregate across sites through internal service auth.

## Envelope

Every uploaded event should include:

- `schema_version`: current value `2026-06-01`.
- `plugin_slug`: one of `magick-ai-abilities`, `magick-ai-core`,
  `magick-ai-adapter`, or `npcink-cloud-addon`.
- `plugin_version`: emitter plugin version.
- `source`: normally `local`.
- `event_kind`: stable dotted event name.
- `status`: `ok`, `warning`, or `error`.
- `emitted_at`: UTC timestamp from the emitting plugin when available.
- `captured_at`: UTC timestamp from the addon collector when available.

Recommended fields:

- `event_id`: stable event id when the emitter can provide one.
- `latency_ms`: non-negative integer latency for completed operations.
- `error_code`: stable dotted error code when `status` is `error`.
- `status_detail`: short redacted diagnostic label.
- `ability_id`, `proposal_id`, `correlation_id`, `adapter_request_id`.
- `method`, `route`, `status_code` for redacted HTTP-style adapter events.
- Count fields such as `proposal_count`, `blocked_count`, `executed_count`,
  and `failed_count` for batch summaries.

## Forbidden Data

Events must not include:

- prompts, completions, generated content, or WordPress post/comment bodies
- raw ability definitions, raw callback payloads, raw requests, or raw responses
- API keys, secrets, cookies, nonces, authorization headers, signatures, tokens
- customer PII beyond stable ids already required for routing and support
- database connection strings, filesystem paths, or server environment dumps

Cloud summary responses must not expose `payload_json` or any raw event payload.

## Event Naming

Use lowercase dotted names:

`<domain>.<object>.<action>[.<outcome>]`

Examples:

- `abilities.catalog.changed`
- `abilities.callback.completed`
- `core.preflight.completed`
- `core.preflight.blocked`
- `adapter.openclaw.dispatch.completed`
- `adapter.openclaw.dispatch.failed`
- `addon.batch.uploaded`

Registration-class events must be aggregated and rate-limited. Do not emit a
per-ability registration event for every ability on every request.

## Deduplication and Rate Limits

Cloud deduplication prefers stable `event_id` semantics. When `event_id` is
present, Cloud hashes `site_id`, `key_id`, `plugin_slug`, `event_kind`, and
`event_id`; timestamp drift must not create a second stored event. When
`event_id` is absent, Cloud falls back to `site_id`, `key_id`, `plugin_slug`,
`event_kind`, `emitted_at`, `captured_at`, `correlation_id`, and
`adapter_request_id`.

Emitters should provide `event_id` where practical. Stable IDs should represent
the semantic operation being reported, not the collector upload attempt.

Registration-class events should emit only when:

- the ability catalog hash changes
- the plugin is activated
- a manual refresh explicitly asks for it
- the plugin version changes

Same catalog hash emissions should be limited to at most once per plugin version
per 24 hours unless a version-change rule requires a fresh event.

## Read Model

Cloud summaries may expose:

- totals: event, ok, error, success rate, average latency, last seen
- plugin summaries and event-kind summaries
- hourly timeline buckets
- site health state and attention items
- attention workflow state for operator acknowledgement, mute, resolve, and
  clear-state actions
- daily or weekly digest text generated from metadata-only summaries
- error-code ranking and recent metadata-only errors

Cloud summaries must not expose:

- raw payloads
- control actions that mutate local plugin state
- plugin registry edits or ability publication controls

## Retention

Raw `plugin_observability_events` rows are retained for 180 days by default,
based on Cloud `received_at`. The ops cadence worker may purge rows older than
that cutoff. Portal and Admin summaries are read models over retained
metadata-only events; they do not require indefinite raw event storage.

Retention cleanup must not call back into WordPress, mutate local plugin
settings, or change local approval/router/write state.

## Health State

Summary health state is advisory and read-only:

- `ok`: recent data is present and no error pressure is detected.
- `warning`: errors, stale reporting, missing expected plugins, or elevated
  latency need review.
- `error`: high error rate or severe freshness failure requires operator
  attention.
- `inactive`: no events are available in the selected window.

Health state must not be used as proof that local WordPress execution is safe.
It is an operations signal, not a local governance decision.

## Attention Items

Attention items are short, bounded diagnostics for operators and users. Each
item should include:

- `attention_key`: stable hash for this watch item
- `severity`: `warning` or `error`
- `code`: stable dotted reason code
- `title`: short display label
- `detail`: one sentence explanation
- `workflow_status`: `active`, `acknowledged`, `muted`, or `resolved`
- optional `site_id`, `plugin_slug`, `event_kind`, `error_code`
- optional `suggested_action`
- optional `state` with `muted_until`, `operator_note`, and `updated_at`

Portal may show site-scoped attention items. Admin may show cross-site attention
items. Neither surface should expose raw payloads.

## Attention Workflow

The attention workflow is an operator display workflow only. It may store:

- `attention_key`
- `attention_code`
- optional site, plugin, event-kind, and error-code dimensions
- `workflow_status`
- optional mute expiry and operator note

It must not mutate local plugin settings, local approval state, ability
definitions, OpenClaw routing, WordPress content, or any local execution truth.

## Digest

Summary responses may include a `digest` object for Portal and Admin:

- `period_label`: `daily` or `weekly`
- `window_hours`
- `headline`
- `bullets`
- optional top plugin and top error identifiers

Digest text is generated only from bounded metadata summaries. It must not
include prompts, generated content, raw payloads, secrets, or PII beyond stable
site/plugin/error identifiers already allowed by this contract.
