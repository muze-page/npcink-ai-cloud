# Site Monitoring Observability v1

Status: implemented

Date: 2026-06-10

## Purpose

Site monitoring gives WordPress site owners and operators a small operating
surface for Cloud health. It should answer:

- Is this site healthy enough to keep using Cloud features?
- Which item needs attention first?
- Where should the operator inspect detail?

It must not become a second control plane. WordPress remains the local content,
approval, and write owner. Cloud monitoring is read-only telemetry,
diagnostics, and usage visibility.

## Surfaces

Portal `/portal/monitoring` is for site owners:

- show four header metrics: site health, action required, quota pressure, last
  activity;
- show only the top three `action_required` items on the overview;
- show three detail entries: Plugins, Media, Vector;
- keep detailed tables, timelines, errors, and ranked breakdowns inside the
  detail tabs or Admin.

Admin pages are for operators:

- cross-site aggregation;
- site/plugin/media/vector tables;
- timelines and ranked error codes;
- recent failures and diagnostic detail.

## Contract

Portal overview uses:

- endpoint: `GET /portal/v1/sites/{site_id}/monitoring-overview`
- query: `window_hours`, 1 to 168, default 24
- response contract: `magick-site-monitoring-overview-v1`

Top-level fields:

- `health`: site-level status and score;
- `action_required`: prioritized operator items;
- `quota`: current period runs/tokens/cost pressure;
- `activity`: recent Cloud activity counts;
- `components`: per-area status for API key, plugins, media, vector, runtime,
  quota, and activity.

Sensitive fields are not exposed:

- API key id, secret hash, plaintext secret, signing secret;
- raw plugin payload JSON;
- raw prompt, generated content, callback input, request body, response body;
- raw search query text, chunk text, embeddings, source document payloads.

## Health Scoring

Health score is intentionally conservative. It is not an SLA. It is a site
owner triage signal.

Component scores are computed independently, then site health uses the lowest
active component score.

Statuses:

- `ok`: score 90 to 100;
- `warning`: score 70 to 89;
- `error`: score below 70;
- `inactive`: no meaningful activity in the component.

Current component inputs:

- API key: active key count, expiry within seven days, recent key use;
- Plugins: plugin observability health and active attention items;
- Media: media job failure count and media health;
- Vector: search no-hit rate, empty index with search traffic, vector health;
- Runtime: rolling 24 hour run success rate and P95 latency;
- Quota: runs/tokens/cost usage ratio and over-limit state;
- Activity: whether Cloud has seen recent site activity.

## Action Required

`action_required` is the primary Portal decision surface. It should stay short,
stable, and actionable.

Each item contains:

- `code`: stable machine-readable reason;
- `severity`: `warning` or `error`;
- `source`: routing source;
- `title`: short operator-facing label;
- `detail`: one sentence explaining current evidence;
- `suggested_action`: one action the user can take;
- `sort_weight`: stable priority order within severity.

Current triggers:

- `site_monitoring.connection_credential_missing`: no active site connection credential;
- `site_monitoring.api_key_expiring`: active key expires within seven days;
- `site_monitoring.api_key_stale`: active key has not been used in seven days;
- `site_monitoring.no_activity`: active key exists, but Cloud saw no activity;
- `plugin_observability.*`: active plugin attention items from plugin telemetry;
- `site_monitoring.media_failures`: failed media jobs in the selected window;
- `site_monitoring.vector_no_hit_pressure`: vector no-hit rate at least 25%;
- `site_monitoring.vector_index_empty`: searches exist, but no chunks are
  recorded;
- `site_monitoring.runtime_success_rate`: runtime success rate below 97%;
- `site_monitoring.quota_*`: quota usage at least 90% or over limit.

The Portal overview renders only the first three items. Remaining items stay in
detail tabs/Admin to avoid turning the overview into a diagnostic wall.

## Action Targets

Portal action rows are clickable. The UI routes by `source`:

- `plugins`: switch to the Plugins tab;
- `media`: switch to the Media tab;
- `vector`: switch to the Vector tab;
- `quota` or `runtime`: open `/portal/usage?site={site_id}`;
- `connection`, `keys`, or `activity`: open `/portal/sites/{site_id}`;
- unknown source: stay on the overview.

The backend contract stays simple: it emits stable source and code values. The
Portal owns navigation mapping.

## Portal vs Admin Boundary

Portal should not add new default-visible charts unless they directly change
the site owner's next action.

Allowed in Portal overview:

- site health score/status;
- action item count;
- top quota pressure;
- last activity;
- top three action items;
- Plugins/Media/Vector status entry cards.

Allowed in Portal detail tabs:

- site-scoped plugin events and recent errors;
- site-scoped media jobs, failures, format mix, and timeline;
- site-scoped vector search/index quality, no-hit rate, snapshots, and errors.

Admin-only by default:

- cross-site rankings;
- global error-code rankings;
- long recent-error lists;
- full timeline comparisons;
- raw operator diagnostics;
- retention and cleanup evidence.

## Change Rules

Before adding a new Portal metric, check:

1. Does it change what the site owner should do now?
2. Can it be explained in one short sentence?
3. Does it avoid exposing content, prompts, secrets, or raw payloads?
4. Would it be better as a detail-tab or Admin-only diagnostic?

If the answer to 1 is no, do not add it to the Portal overview.

## Observation Plan

Observe real data for three to seven days before changing thresholds.

Review:

- whether `action_required` is too noisy;
- whether health score causes false alarm;
- whether plugin inactivity is expected for quiet sites;
- whether quota warnings arrive early enough;
- whether users click the expected target after seeing an action item.

Tune thresholds only after real data shows repeated false positives or missed
issues.
