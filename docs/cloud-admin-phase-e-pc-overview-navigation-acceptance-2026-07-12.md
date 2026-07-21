# Cloud Admin Phase E — PC Overview and Navigation Acceptance

Date: 2026-07-12
Primary viewport: 1440 × 1050 desktop
Surfaces: `/admin` and the desktop quick switcher

## Change envelope

- Focused module: PC admin overview and desktop navigation discoverability.
- Intended change: keep the overview decision-oriented, reduce duplicated first-screen destinations, move supporting telemetry under disclosure, and make diagnostic child routes searchable without expanding the sidebar.
- Explicit non-goals: no API ownership change, no mutation, no new Cloud control plane, and no mobile/tablet layout redesign in this phase.
- Public contracts touched: presentation and client-side navigation only. Existing overview and diagnostic endpoints remain unchanged.
- Rollback: revert the overview composition, command palette contextual items, translations, dedicated tests, and this record.

## Accepted PC operator model

1. Read one platform conclusion and four core metrics.
2. Follow the single recommended next action.
3. Review no more than two immediate watch items in the conclusion panel.
4. Open one of four canonical work destinations: tickets, service status, customers, or runtime diagnostics.
5. Use customer/Portal-user lookup for support questions.
6. Expand platform usage and supporting evidence only when the first-screen conclusion is insufficient.
7. Use the desktop quick switcher to open plugin, media, vector, Agent feedback, or Operations Advisor diagnostic child routes.

## Functional corrections

- Provider and service-settings links no longer duplicate the persistent sidebar in the overview destination grid.
- The runtime/usage snapshot no longer competes with the primary work surface; it is inside extended evidence.
- The overview header exposes one primary next action instead of two potentially overlapping actions.
- Known runtime alert titles and summaries are localized before appearing in the overview.
- Initial loading and failure preserve the overview shell; failure provides a safe retry.
- The overview request has a twelve-second timeout instead of remaining in loading indefinitely.
- Diagnostic child pages are discoverable in the quick switcher while remaining grouped under the single Runtime Diagnostics sidebar entry.

## PC visual acceptance

- 1440 × 1050 overview hierarchy passed real-browser inspection.
- Four canonical destination cards fit in one desktop row.
- The primary conclusion, metrics, action, and first watch item remain visible before the lower evidence sections.
- The quick switcher shows one clear result and its Diagnostics group when searching for “媒体”.
- Known provider error evidence renders in Chinese instead of leaking backend English copy.
- Existing mobile compatibility remains intact, but mobile/tablet refinement is explicitly deferred.

## Automated acceptance

- Admin overview/navigation static contract passed.
- Admin information architecture contract passed for all 23 routes.
- Targeted ESLint passed.
- Frontend type-check passed.
- Dedicated overview/navigation E2E: 3 passed.

## Next phase

Continue the PC-only consistency audit across the remaining admin detail and configuration routes. Prioritize pages that still expose oversized explanation blocks, duplicate primary actions, permanent success cards, or evidence before the main task.
