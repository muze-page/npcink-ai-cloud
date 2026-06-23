# Plugin Observability Plugin-Side Handoff

Status: handoff prompts

Date: 2026-06-03

Use this document when delegating the remaining WordPress plugin-side work to
separate AI sessions. The Cloud implementation is already able to ingest and
display real metadata-only events. The next work is to make each plugin provide
stable, low-noise trigger coverage and tests.

## Current Real-Chain Evidence

Local smoke site:

- WordPress site: `https://npcink.local`
- Cloud site id: `site_npcink_local`
- Cloud base URL: `http://127.0.0.1:8010`
- Cloud Addon: verified and monitoring enabled

Observed Cloud Addon flush result:

- Addon buffer flushed successfully.
- Final buffer count reached `0`.
- Portal showed `1,050` site-scoped real events and `44` errors.
- Admin showed `1,117` cross-site events and `45` errors.

Observed event kinds in the local buffer included:

- `abilities.catalog.changed`
- `abilities.callback.completed`
- `core.commit.preflight`
- `core.proposal.create`
- `core.proposal.approve`
- `core.proposal.reject`
- `core.proposal.plan_ingest`
- `adapter.core.request`
- `adapter.proposal.create`
- `adapter.commit.preflight`
- `adapter.proposal.plan_ingest`

Observed registration-class behavior:

- `abilities.catalog.changed` appeared sparsely.
- There was no per-ability registration flood in the latest real buffer.

## Shared Requirements

All plugin-side changes must keep this boundary:

- Cloud Addon is the only uploader.
- Plugins emit local events through `npcink_observability_event`.
- Events are metadata-only.
- Do not emit prompts, generated content, raw callback payloads, raw HTTP bodies,
  request/response payloads, auth headers, keys, cookies, nonces, signatures,
  tokens, or WordPress content bodies.
- Do not make Cloud a second ability registry, approval plane, OpenClaw truth,
  router truth, or WordPress write owner.

All plugins should prefer stable fields:

- `schema_version`
- `plugin_slug`
- `plugin_version`
- `source`
- `event_kind`
- `event_id`
- `status`
- `error_code`
- `latency_ms`
- `ability_id`, `proposal_id`, `correlation_id`, or `adapter_request_id` where
  relevant
- `emitted_at`

## Prompt: magick-ai-abilities

Copy this into the `magick-ai-abilities` AI session:

```text
You are working in /Users/muze/gitee/magick-ai-abilities.

Goal: finish plugin-side observability trigger coverage for Cloud monitoring.

Context:
- Cloud docs are in /Users/muze/gitee/npcink-cloud/docs:
  - plugin-observability-v1.md
  - plugin-observability-event-catalog.md
  - plugin-observability-emitter-examples.md
  - plugin-observability-e2e-acceptance.md
  - plugin-observability-plugin-side-handoff.md
- Cloud Addon is the only uploader. This plugin only emits local
  npcink_observability_event metadata.
- Do not emit prompts, generated content, raw callback payloads, auth material,
  or WordPress content bodies.

Required work:
1. Verify that registration-class events are sparse:
   - emit abilities.catalog.changed only on plugin activation, manual refresh,
     plugin version change, or ability catalog hash change;
   - repeated ordinary boot/page refresh must not emit per-ability registration
     events and must not emit a same-hash catalog burst.
2. Add or verify stable callback success and failure observability:
   - abilities.callback.completed for successful callback execution;
   - abilities.callback.failed for WP_Error, thrown exception, timeout, or
     callback error envelope where the codebase can simulate it safely.
3. Ensure event_id is stable enough for dedupe and does not include raw payloads.
4. Add focused tests for:
   - same catalog hash does not create repeated catalog changed events;
   - catalog hash change creates one additional catalog changed event;
   - callback success emits abilities.callback.completed;
   - callback failure emits abilities.callback.failed with a stable error_code;
   - no payload_json/raw callback input is emitted.
5. Run the repository's existing unit/smoke checks and report exact commands.

Acceptance:
- Latest real buffer should still show no registration flood.
- Cloud Portal should show magick-ai-abilities with callback event counts.
- A simulated callback failure should produce a metadata-only recent error.
```

## Prompt: magick-ai-core

Copy this into the `magick-ai-core` AI session:

```text
You are working in /Users/muze/gitee/magick-ai-core.

Goal: finish plugin-side observability trigger coverage for Core governance,
approval, preflight, and audit metadata.

Context:
- Cloud docs are in /Users/muze/gitee/npcink-cloud/docs:
  - plugin-observability-v1.md
  - plugin-observability-event-catalog.md
  - plugin-observability-emitter-examples.md
  - plugin-observability-e2e-acceptance.md
  - plugin-observability-plugin-side-handoff.md
- Cloud Addon is the only uploader. Core only emits local
  npcink_observability_event metadata.
- Core remains the local governance truth. Cloud must not approve, reject,
  preflight, mutate proposals, or write WordPress content.

Required work:
1. Inventory current Core observability event names. Real Cloud smoke has seen:
   - core.commit.preflight
   - core.proposal.create
   - core.proposal.approve
   - core.proposal.reject
   - core.proposal.plan_ingest
2. Decide whether to keep these as canonical Core event kinds or introduce
   aliases that match the Cloud examples. Prefer low churn: if smoke/tests
   already rely on current names, update docs/tests to make them canonical
   rather than renaming blindly.
3. Ensure preflight success and blocked/failed paths emit stable metadata:
   - successful commit preflight;
   - blocked proposal/preflight path;
   - proposal create/approve/reject;
   - plan ingest where applicable.
4. Ensure error events use stable error_code values and never include raw
   proposal payloads, approval notes, generated content, or policy payloads.
5. Add focused tests proving:
   - create/approve/reject emits metadata events;
   - blocked preflight emits warning/error metadata;
   - successful preflight emits ok metadata;
   - payloads remain redacted/bounded.
6. Run the repository's existing unit/smoke checks and report exact commands.

Acceptance:
- Cloud Portal should show magick-ai-core with proposal/preflight event counts.
- Core error pressure should be explainable by stable error_code values.
- Cloud must remain read-only and must not become a second approval plane.
```

## Prompt: magick-ai-adapter

Copy this into the `magick-ai-adapter` AI session:

```text
You are working in /Users/muze/gitee/magick-ai-adapter.

Goal: finish plugin-side observability trigger coverage for Adapter, including
OpenClaw dispatch, Core request relay, proposal handoff, commit preflight, and
failure paths.

Context:
- Cloud docs are in /Users/muze/gitee/npcink-cloud/docs:
  - plugin-observability-v1.md
  - plugin-observability-event-catalog.md
  - plugin-observability-emitter-examples.md
  - plugin-observability-e2e-acceptance.md
  - plugin-observability-plugin-side-handoff.md
- Cloud Addon is the only uploader. Adapter only emits local
  npcink_observability_event metadata.
- Adapter stays thin. Core remains governance truth. WordPress final writes stay
  local and governed.

Required work:
1. Inventory current Adapter observability event names. Real Cloud smoke has
   seen:
   - adapter.core.request
   - adapter.proposal.create
   - adapter.commit.preflight
   - adapter.proposal.plan_ingest
2. Decide whether to keep these as canonical Adapter event kinds or introduce
   aliases matching the Cloud examples. Prefer low churn: if current smoke/tests
   rely on current names, update docs/tests to make them canonical rather than
   renaming blindly.
3. Add or verify stable OpenClaw dispatch observability:
   - adapter.openclaw.dispatch.completed for successful dispatch;
   - adapter.openclaw.dispatch.failed for channel/Core/dispatch failures.
4. Ensure Core relay calls and proposal handoff emit metadata with:
   - method/route/status_code where useful;
   - adapter_request_id or correlation_id where available;
   - stable error_code for failures.
5. Ensure no raw OpenClaw request, raw response, write input, prompt, generated
   content, auth header, or secret is emitted.
6. Add focused tests proving:
   - Core relay success/failure emits metadata;
   - proposal create/handoff emits metadata;
   - commit preflight success/failure emits metadata;
   - OpenClaw dispatch success/failure emits metadata;
   - emitted events are redacted/bounded.
7. Run the repository's existing unit/smoke checks and report exact commands.

Acceptance:
- Cloud Portal should show magick-ai-adapter with request/dispatch event counts.
- Adapter failures should affect health, attention, error ranking, and recent
  errors through stable metadata-only error_code values.
- Cloud must not see raw OpenClaw or WordPress write payloads.
```

## Prompt: npcink-cloud-addon

Copy this into the `npcink-cloud-addon` AI session if addon-side refinement is
needed:

```text
You are working in /Users/muze/gitee/npcink-cloud-addon.

Goal: harden the Addon observability collector and local monitoring status.

Context:
- Cloud docs are in /Users/muze/gitee/npcink-cloud/docs:
  - plugin-observability-v1.md
  - plugin-observability-e2e-acceptance.md
  - plugin-observability-plugin-side-handoff.md
- Cloud Addon is the only uploader. Other plugins emit local
  npcink_observability_event metadata.

Required work:
1. Verify collection is disabled unless settings are verified and
   monitoring_enabled is true.
2. Verify buffer bounds and batch size:
   - buffer cap remains bounded;
   - batch flush is bounded;
   - failed upload keeps events buffered;
   - successful upload removes accepted events.
3. Verify local status is useful and not misleading:
   - stale timestamp errors from historical attempts are cleared after a fresh
     successful flush;
   - last_upload_ok, last_uploaded_at, last_upload_error, total_uploaded, and
     buffer_count are accurate.
4. Verify summary refresh uses Cloud metadata summary and stores only sanitized
   summary fields.
5. Verify addon upload telemetry is sparse. Do not emit one addon telemetry
   event for every uploaded plugin event.
6. Add tests for disabled, verified-enabled, failed upload, successful upload,
   bounded buffer, and sanitized summary behavior.
7. Run the repository's existing unit/smoke checks and report exact commands.

Acceptance:
- LocalWP direct flush can drain the buffer to 0.
- Cloud Portal/Admin show real events after flush.
- No raw payloads, secrets, signatures, keys, cookies, tokens, or auth headers
  are stored in addon monitoring options.
```

