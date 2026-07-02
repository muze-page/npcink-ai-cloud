# Site Monitoring Discussion Summary

Status: historical summary

Date: 2026-06-10

Related current contract:

- `docs/site-monitoring-observability-v1.md`

Related implementation and handoff documents:

- `docs/plugin-observability-v1.md`
- `docs/plugin-observability-event-catalog.md`
- `docs/plugin-observability-plugin-side-handoff.md`
- `docs/plugin-observability-dedupe-smoke-2026-06-03.md`
- `docs/superpowers/specs/2026-06-03-media-observability-design.md`
- `docs/superpowers/specs/2026-06-03-vector-observability-design.md`
- `docs/site-knowledge-runtime-contract-v1.md`

## Why This Exists

This document summarizes the product and engineering discussion that led to the
current Npcink AI Cloud monitoring design. It is intentionally historical: use
it to understand the trade-offs and avoid re-expanding the Portal monitoring
surface without a clear operational reason.

The current implementation target is:

- Cloud can collect and analyze service telemetry.
- WordPress site owners see a compact, actionable Portal view.
- Cloud operators keep the detailed Admin diagnostics.
- Cloud does not become a second WordPress control plane.

## Initial Goal

The original request was to make Cloud-side statistics and monitoring more
systematic and professional for the Magick AI plugin series:

- `npcink-abilities-toolkit`: ability definitions and ability callback activity;
- `npcink-governance-core`: governance, approval, preflight, and audit activity;
- `npcink-ai-client-adapter`: OpenClaw channel adaptation and calls into Core and
  Abilities APIs.

Important product constraint:

- The three plugins can be installed and listed independently on WordPress.org.
- Monitoring should only be uploaded when `npcink-cloud-addon` is installed
  and active.
- The Cloud Addon is the uploader. The other plugins only emit local
  metadata-only events.

This prevented each plugin from becoming a direct Cloud client and kept the
Cloud integration opt-in.

## Plugin Observability Direction

The first monitoring line was plugin observability.

Key decisions:

- Events are metadata-only.
- Cloud Addon flushes buffered local events.
- `event_id` and dedupe keys are stable.
- Registration-class events must be low-noise.
- `abilities.catalog.changed` should only be emitted on activation, manual
  refresh, plugin version change, or catalog hash change.
- Repeated page loads or ordinary bootstrap must not emit per-ability
  registration floods.

Cloud-side work included:

- event ingestion;
- dedupe;
- admin summary;
- Portal site-scoped summary;
- retention cleanup, later set to 180 days;
- handoff documentation for plugin-side implementation.

Real smoke evidence later showed:

- Cloud Addon could flush real buffered events;
- Portal/Admin data appeared;
- stable `event_id` dedupe worked;
- registration-class noise was under control after plugin-side changes.

Real plugin event kinds observed during local smoke included:

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

These names should be treated as existing low-churn event vocabulary unless a
future migration plan deliberately aliases or replaces them.

## Portal vs Admin Split

The early implementation exposed useful data but created an important product
question: should site administrators see the same kind of observability dashboard as
Cloud admins?

Decision:

- Portal is for site owners and should answer "what needs attention now?"
- Admin is for operators and can show cross-site tables, timelines, error
  rankings, recent failures, and diagnostic detail.

This became the core display boundary.

Portal should not become a dense BI dashboard. It should stay close to an
operating surface:

- state;
- action required;
- where to inspect next.

## Media Observability

After Cloud gained media derivative processing, monitoring was extended to
media jobs.

Useful data:

- jobs total;
- succeeded and failed jobs;
- success rate;
- processing duration and P95;
- queue wait;
- bytes saved and compression ratio;
- active artifacts and artifact storage;
- recent failures and error codes.

Decision:

- Admin can show tables, timelines, storage, and failures.
- Portal overview should only surface media when it affects site health or
  creates an action item.
- Portal media detail can show site-scoped processing details.

## Vector Observability

After Cloud gained site knowledge / vector features, monitoring was extended to
indexing and search quality.

Useful data:

- index job count;
- indexed documents and chunks;
- failed documents;
- current index snapshot;
- search query count;
- no-hit count and rate;
- average and P95 search latency;
- intent mix;
- vector backend and embedding metadata.

Privacy boundary:

- no raw query text;
- no chunk text;
- no embeddings;
- no source document payloads.

Decision:

- Admin can show vector health, site rankings, intent mix, snapshots, errors,
  and timelines.
- Portal detail can show site-scoped vector quality.
- Portal overview should only surface vector issues such as high no-hit rate or
  searches against an empty index.

## Three Monitoring Areas and Tabs

Once plugin, media, and vector observability existed, the Portal page became too
long.

Decision:

- Use tabs under `/portal/monitoring`:
  - Overview;
  - Plugins;
  - Media;
  - Vector.

This allowed detail to stay available without forcing every site owner to scan
every table and chart.

## Site Monitoring Overview

A higher-level site monitoring overview was added to combine signals into one
site owner summary.

Backend contract:

- `GET /portal/v1/sites/{site_id}/monitoring-overview`
- response contract: `magick-site-monitoring-overview-v1`

Aggregated inputs:

- API key status;
- plugin health and attention items;
- media health;
- vector health;
- runtime usage summary;
- quota/budget pressure;
- latest Cloud activity.

Output:

- `health`;
- `action_required`;
- `quota`;
- `activity`;
- `components`.

The service intentionally reuses existing observability and commercial-policy
services instead of creating a separate source of truth.

## Complexity Review

After adding the overview, we reviewed whether the monitoring surface had become
too complex.

Conclusion:

- The collection and aggregation layer is valuable and should remain.
- The Portal default view was becoming too dense.
- The Admin/detail surfaces are the right place for charts, rankings, and deep
  diagnostics.

Decision:

- Stop adding new metrics to the Portal overview.
- Simplify the overview to the minimum set that supports a site owner decision.

Current Portal overview shape:

- four header metrics:
  - Site health;
  - Action required;
  - Quota pressure;
  - Last activity;
- top three action items;
- three detail entries:
  - Plugins;
  - Media;
  - Vector.

Removed from the overview body:

- duplicate second metric strip;
- standalone quota/cost panel;
- long action list;
- extra explanatory data that did not change the next action.

## Action Required Routing

Action items became clickable to reduce user effort after an issue is shown.

Routing is owned by the Portal UI and based on `source`:

- `plugins`: switch to Plugins tab;
- `media`: switch to Media tab;
- `vector`: switch to Vector tab;
- `quota` or `runtime`: open `/portal/usage?site={site_id}`;
- `keys` or `activity`: open `/portal/sites/{site_id}`;
- unknown source: remain on overview.

This keeps the backend contract simple and makes the Portal more operational:
show the issue, then take the user to the most relevant inspection surface.

## Current Implementation State

Current implemented areas:

- plugin observability;
- media derivative observability;
- vector/site knowledge observability;
- site-level monitoring overview;
- Portal monitoring tabs;
- Admin detail surfaces;
- click-through `action_required` rows;
- current monitoring contract documentation.

Current reference document:

- `docs/site-monitoring-observability-v1.md`

Recent simplification commit:

- `c8122b8 Simplify portal monitoring overview`

Recent verification used:

- frontend type check;
- frontend lint;
- `git diff --check`;
- browser smoke of `/portal/monitoring`;
- action-row click smoke confirming a plugin action navigated to
  `/portal/monitoring?tab=plugins`.

## Working Rules for Future Changes

Before adding a Portal overview metric, ask:

1. Does this change what the site owner should do now?
2. Can the result be explained in one short sentence?
3. Is it safe metadata only?
4. Would it be better as a detail-tab or Admin-only diagnostic?

If the answer to the first question is no, do not add it to the Portal
overview.

Preferred future additions:

- improve action routing;
- tune thresholds after real data;
- add concise notification summaries if action noise is stable;
- improve Admin diagnostics where operators need deeper evidence.

Avoid:

- adding more overview cards;
- adding charts to the overview;
- exposing raw payloads, content, prompts, secrets, or raw search text;
- making Cloud responsible for WordPress writes, approvals, or local plugin
  control-plane state.

## Observation Plan

Observe real data for three to seven days before changing thresholds.

Review:

- whether `action_required` is too noisy;
- whether plugin inactivity should be warning or normal for quiet sites;
- whether site health score is too strict;
- whether quota warnings arrive early enough;
- whether users click the expected detail target after seeing an action item.

Only tune thresholds after real data shows repeated false positives or missed
issues.
