# Site Diagnostic Advisor Closeout - 2026-06-24

Status: local closeout summary.

Related docs:

- `docs/internal-ai-advisor-v1.md`
- `docs/site-monitoring-observability-v1.md`
- `docs/site-monitoring-discussion-summary-2026-06.md`
- `docs/plugin-observability-v1.md`
- `docs/media-derivative-operations-runbook-v1.md`
- `docs/site-knowledge-runtime-contract-v1.md`

## Why This Work Happened

The starting request was to review recent discussion topics from two WordPress
ecosystem forums and identify ideas that were practical for the current Cloud
project:

- `https://guaqi.com/topic`
- `https://www.zibll.com/forums`

The discussion narrowed to one candidate feature: a site-level diagnostic
advisor. The useful signal was not "add another dashboard", but "turn scattered
monitoring signals into an operator-readable explanation and next step".

The project already had several ingredients:

- plugin observability;
- media derivative observability;
- site knowledge/vector observability;
- usage, quota, and runtime health data;
- Portal monitoring tabs;
- an Internal AI Advisor contract.

That made the feature a good fit if it stayed small and read-only.

## Product Decision

We decided to implement a bounded `Site diagnostics advisor` instead of a broad
forum-inspired feature set.

The feature answers:

- What is currently wrong with this site?
- Which evidence created that diagnosis?
- What is the likely cause?
- Where should the operator inspect next?
- Has the diagnostic item already been acknowledged?

The feature does not answer by taking action on WordPress. It only explains and
routes the user to existing evidence surfaces.

## Boundary Decision

Cloud must remain a runtime/detail/advisor layer. It must not become:

- a second WordPress control plane;
- a second workflow registry;
- a second ability registry;
- a second source of truth for local WordPress writes.

Therefore the diagnostic advisor is constrained to:

- `suggestion_only` output;
- operator review required;
- no automatic repair;
- no direct WordPress write;
- no raw plugin payload exposure;
- no new workflow engine;
- no new database table for this phase.

This keeps the feature aligned with the existing Cloud boundary: Cloud may
summarize health, diagnostics, and next steps, but final WordPress action stays
local and reviewable.

## Implemented Backend Shape

The backend implementation extends the existing Internal AI Advisor service.

Primary service:

- `InternalAIAdvisorService.get_site_diagnostic_advisor(...)`

Internal route:

- `GET /internal/service/advisor/site-diagnostics?site_id=...&window_hours=24`

Portal route:

- `GET /portal/v1/sites/{site_id}/diagnostic-advisor?window_hours=24`

Inputs:

- `SiteMonitoringOverviewService.get_summary(...)`
- plugin observability attention items;
- media health;
- vector/site-knowledge health;
- runtime and quota signals;
- site activity and key state.

The advisor returns up to three prioritized diagnostic items.

Each diagnostic item includes:

- `diagnostic_key`
- `code`
- `severity`
- `source`
- `title`
- `evidence_summary`
- `likely_cause`
- `next_step`
- `recommended_action_id`
- `workflow_status`
- `status_detail`
- `evidence_window`
- `last_updated_at`
- `operator_review_required`
- `direct_wordpress_write`

Top-level response additions:

- `diagnostic_workflow`
- `evidence_window`
- `safety`

The `safety` block explicitly records:

```json
{
  "write_posture": "suggestion_only",
  "direct_wordpress_write": false,
  "operator_review_required": true,
  "automatic_repair_allowed": false,
  "raw_payload_exposed": false
}
```

## Implemented Portal Shape

The Portal monitoring page now shows a `Site diagnostics` panel on the Overview
tab.

Location:

- `/portal/monitoring?site=<site_id>`

The panel shows:

- status/severity;
- summary;
- `suggestion only` badge;
- new/acknowledged diagnostic counts;
- evidence window;
- generated time;
- each diagnostic item's title, source, severity, workflow status, evidence,
  likely cause, next step, and last update time.

Clicking a diagnostic item routes to the existing evidence surface:

- plugin issues -> `tab=plugins`
- media issues -> `tab=media`
- vector issues -> `tab=vector`
- runtime/quota issues -> `/portal/usage`
- key/activity issues -> `/portal/sites/{site_id}`

No repair button or apply button was added.

## Current Closed Loop

The implemented loop is now:

```text
monitoring signal
  -> SiteMonitoringOverview action_required
  -> Site Diagnostic Advisor explanation
  -> Portal Site diagnostics panel
  -> click into existing evidence tab/page
  -> existing attention state can mark item acknowledged/muted/resolved
  -> Advisor reflects workflow_status on next read
```

This is stronger than the first MVP loop because the status can flow back into
the diagnostic item. For plugin-derived attention items, the advisor reuses the
existing plugin observability attention state model.

The loop is still intentionally human-operated. It does not automatically fix a
site and it does not create a WordPress proposal.

## What Was Not Built

The following were deliberately left out:

- automatic repair;
- one-click WordPress mutation;
- proposal creation from Cloud;
- a new Portal control console;
- a new notification system;
- a new diagnostic persistence table;
- a new workflow engine or scheduler;
- cross-customer Portal diagnostics.

These omissions are part of the boundary, not unfinished implementation.

## Verification

Backend and frontend verification completed during implementation:

- Python syntax checks for advisor and route modules;
- `ruff check` for touched backend files and tests;
- targeted backend tests for internal and Portal diagnostic advisor routes;
- related monitoring and plugin observability backend tests;
- frontend `type-check`;
- frontend `lint`;
- Portal Playwright e2e for the monitoring path.

Important test assertions added or extended:

- raw `payload_json` does not leak into advisor response;
- Portal route is site-scoped and rejects unauthorized site admins;
- diagnostic item exposes `workflow_status`;
- diagnostic item exposes `evidence_window`;
- after an existing plugin attention item is acknowledged, the advisor returns
  `workflow_status = acknowledged`;
- Portal displays the diagnostic panel and routes to the plugin evidence tab.

## Files Touched By This Feature Line

Core backend:

- `app/domain/advisor/service.py`
- `app/domain/observability/site_monitoring_overview.py`
- `app/api/routes/service.py`
- `app/api/routes/portal.py`

Portal frontend:

- `frontend/src/lib/portal-client.ts`
- `frontend/src/app/portal/monitoring/page.tsx`

Tests:

- `tests/api/test_service_routes.py`
- `tests/api/test_portal_routes.py`
- `frontend/tests/e2e/portal-workspace-path.spec.ts`

Docs:

- `docs/internal-ai-advisor-v1.md`
- this closeout document

## Current Assessment

The feature is now complete enough to stop product expansion and move to real
site validation.

It forms a practical closed loop for review and diagnosis:

- signal is collected;
- Cloud explains the signal;
- Portal shows what to inspect;
- the operator can inspect the evidence;
- existing attention state can be reflected back into the advisor.

It is not yet a full automated operations loop, and that is the correct product
boundary for the current stage.

## Recommended Next Step

Do not add more UI or automation immediately.

Next useful step:

1. Run this against real site telemetry.
2. Record which diagnostic items appear.
3. Check whether the likely cause and next step are correct.
4. Count false positives or noisy items.
5. Only then decide whether to add persistence, notifications, or richer
   operator workflows.

Recommended acceptance questions for real-site validation:

- Does the first diagnostic item match the real problem?
- Can a site admin understand the next step without Cloud operator context?
- Does the click target expose enough evidence?
- Does acknowledging/muting in the existing plugin attention path reduce repeat
  noise?
- Are any raw payloads, cross-site data, or write controls exposed accidentally?

Until real telemetry proves otherwise, this feature should stay bounded as a
read-only diagnostic advisor.
