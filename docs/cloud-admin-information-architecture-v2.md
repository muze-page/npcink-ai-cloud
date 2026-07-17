# Cloud Admin Information Architecture v2

Status: active migration contract.

Purpose: rebuild the platform-admin workspace around operator tasks, object
ownership, risk, and evidence instead of treating every route as a dashboard
made from cards.

This document is the authoritative migration contract for
`frontend/src/app/admin/**`. The existing
`cloud-admin-feedback-and-layout-contract-v1.md` remains authoritative for
mutation feedback and receipt handling; this document defines the larger
information architecture and page-model system around it.

## 1. Product Boundary

The admin workspace is a bounded `platform_admin` service-plane surface. It may
operate Cloud-owned accounts, sites, commercial records, provider connections,
runtime diagnostics, service configuration, and audit evidence.

It must not become:

- a second WordPress control plane;
- a local ability or workflow registry;
- prompt, preset, router, MCP, or OpenClaw truth;
- WordPress approval, preflight, publication, or write authority;
- a customer-facing wallet or unbounded commercial front office.

Cloud-owned writes remain reviewable and auditable. WordPress writes and local
governance remain outside this workspace.

## 2. Design Objective

The refactor is successful when each page answers three questions in one pass:

1. What is the current state?
2. What needs operator attention now?
3. Where is the one appropriate place to act or inspect further?

Visual consistency alone is insufficient. Pages with different jobs must use
different working surfaces while sharing the same status, feedback, action,
responsive, and accessibility contracts.

## 3. Design Principles

1. Organize by operator job, not backend endpoint.
2. Keep one page title and one scope sentence.
3. Put state before explanation.
4. Put the primary task before low-frequency evidence.
5. Use one primary action per section by default.
6. Keep create and edit work in a drawer or dialog when a list remains primary.
7. Keep dangerous actions out of the default action row.
8. Preserve audit receipts without rendering them as permanent success cards.
9. Distinguish loading, empty, filtered-empty, error, success, and disabled.
10. Load low-frequency evidence and large candidate sets on demand.
11. Keep desktop density without making mobile depend on horizontal scrolling
    for the core task.
12. Prefer utility copy over product, architecture, or boundary essays.

## 4. Navigation Domains

The primary navigation is organized into four domains.

### 4.1 Overview

- Platform overview (`/admin`)

### 4.2 Customer Operations

- Customers (`/admin/accounts`)
- Service queue (`/admin/coverage`)
- Tickets (`/admin/support-requests`)
- Packages and credits (`/admin/plans`)
- Portal users (`/admin/portal-users`)

`/admin/subscriptions` is a service-queue view. `/admin/credit-packs` is a
package-and-credit view. They may keep stable routes during migration, but they
must share their parent workspace navigation and visual model.

### 4.3 Runtime Operations

- Model suppliers (`/admin/ai-resources`)
- Runtime profiles (`/admin/runtime-profiles`)
- Search and images (`/admin/external-services`)
- Vector settings (`/admin/vector-settings`)
- Runtime diagnostics (`/admin/troubleshooting`)

Plugin, media, vector, Agent feedback, and Operations Advisor routes are
diagnostic views under Runtime diagnostics. They are not independent top-level
products.

### 4.4 System

- Service settings (`/admin/service-settings`)

### 4.5 Contextual Detail Routes

Customer, site, subscription, package, and ticket detail routes do not appear
as primary navigation entries. They inherit the active parent domain and expose
a stable return path to the originating list or queue.

## 5. Six Page Models

Every admin route must declare exactly one primary page model.

### 5.1 `overview`

Job: decide whether the platform is healthy enough to keep operating and which
queue should be opened first.

Required order:

1. platform conclusion and generated time;
2. no more than five core metrics;
3. no more than three immediate work items;
4. customer/site lookup and primary queue entries;
5. collapsed trends and supporting evidence.

The overview must not duplicate complete customer, usage, diagnostic, or audit
pages.

### 5.2 `queue`

Job: find, filter, prioritize, and open an operational object.

Required order:

1. compact title and create/refresh action;
2. optional compact queue metrics;
3. stable toolbar with tabs, search, filters, and create action;
4. table or task list;
5. contextual inspector or drawer.

Filter state should survive detail navigation and refresh. Row content shows
state, reason, and next action; low-frequency evidence belongs in the inspector.

### 5.3 `detail`

Job: understand one object and perform a bounded follow-up.

Required order:

1. object identity, status, and one main action;
2. compact state and risk summary;
3. current conclusion and recommended next step;
4. task-oriented tabs;
5. related objects and audit entry.

Detail pages must not render all edit forms at once. Mutations use contextual
drawers or dialogs and return focus to their trigger.

### 5.4 `configuration`

Job: inspect readiness, edit one configuration group, test it, and save it.

Required order:

1. readiness summary;
2. configuration group navigation;
3. one active form group;
4. contextual validation and test result;
5. stable save action for the active group.

Configuration pages preserve dirty state, explain disabled actions, never
reveal stored secrets, and warn before abandoning unsaved changes.

### 5.5 `diagnostic`

Job: establish scope, read a health conclusion, inspect anomalies, and open
evidence only when necessary.

Required order:

1. scope and time window;
2. health conclusion;
3. three to five core metrics;
4. trend or distribution;
5. anomaly list;
6. advanced evidence and parameters.

Provider IDs, model IDs, cache keys, raw evidence references, and cost analysis
are advanced detail unless they are the active blocker.

### 5.6 `authentication`

Job: establish an authenticated platform-admin session.

Required order:

1. environment and identity scope;
2. credential field;
3. contextual error;
4. submit action;
5. non-secret help entry.

Authentication pages must not explain backend route structure or expose
operational navigation before authentication.

## 6. Route Migration Matrix

The route may remain stable while its parent workspace or page composition is
migrated. “Merge” below means presentation consolidation, not API or data-truth
consolidation.

| Route | Domain | Page model | Parent workspace | Migration decision |
| --- | --- | --- | --- | --- |
| `/admin` | Overview | `overview` | Overview | Keep; remove duplicated full-page evidence |
| `/admin/login` | Authentication | `authentication` | None | Keep as a single-task page |
| `/admin/accounts` | Customer Operations | `queue` | Customers | Keep as customer register |
| `/admin/accounts/[accountId]` | Customer Operations | `detail` | Customers | Rebuild around overview, commercial, credits, sites, audit tabs |
| `/admin/sites/[siteId]` | Customer Operations | `detail` | Customers | Rebuild around health, coverage, runtime, usage, keys/audit tabs |
| `/admin/coverage` | Customer Operations | `queue` | Service queue | Canonical service follow-up queue |
| `/admin/subscriptions` | Customer Operations | `queue` | Service queue | Keep route; render as subscription-risk view of service queue |
| `/admin/subscriptions/[subscriptionId]` | Customer Operations | `detail` | Service queue | Keep; one reconciliation action and contextual evidence |
| `/admin/support-requests` | Customer Operations | `queue` | Tickets | Keep; split customer conversation from internal handling |
| `/admin/support-requests/[requestId]` | Customer Operations | `detail` | Tickets | Keep; timeline-first ticket detail |
| `/admin/plans` | Customer Operations | `queue` | Packages and credits | Canonical catalog view |
| `/admin/plans/[planId]` | Customer Operations | `detail` | Packages and credits | Keep; edit in contextual drawer |
| `/admin/credit-packs` | Customer Operations | `configuration` | Packages and credits | Keep route; edit one pack at a time |
| `/admin/portal-users` | Customer Operations | `queue` | Portal users | Add as stable secondary navigation entry |
| `/admin/ai-resources` | Runtime Operations | `queue` | Model suppliers | Keep model-provider connections and model visibility together |
| `/admin/external-services` | Runtime Operations | `configuration` | Search and images | Fixed Cloud runtime service directory for web search and stock-image sources |
| `/admin/vector-settings` | Runtime Operations | `configuration` | Providers | Keep vector embedding, storage, and rerank configuration separate from provider queues and diagnostics |
| `/admin/runtime-profiles` | Runtime Operations | `configuration` | Runtime profiles | Keep only platform-tagged Cloud hosted candidate-chain configuration; candidate selection renders only inside edit flow |
| `/admin/troubleshooting` | Runtime Operations | `diagnostic` | Runtime diagnostics | Canonical diagnostic index |
| `/admin/plugin-observability` | Runtime Operations | `diagnostic` | Runtime diagnostics | Shared observability frame |
| `/admin/media-observability` | Runtime Operations | `diagnostic` | Runtime diagnostics | Shared observability frame |
| `/admin/vector-observability` | Runtime Operations | `diagnostic` | Runtime diagnostics | Shared observability frame |
| `/admin/agent-feedback` | Runtime Operations | `diagnostic` | Runtime diagnostics | Read-only quality view |
| `/admin/ai-advisor` | Runtime Operations | `diagnostic` | Runtime diagnostics | Current conclusion first; AI evaluation advanced |
| `/admin/service-settings` | System | `configuration` | Service settings | Keep; one active configuration group at a time |

## 7. State Model

Every primary data surface must implement these states explicitly.

| State | Meaning | Required treatment |
| --- | --- | --- |
| `loading` | Data has not resolved | Preserve shell and show a route/section skeleton |
| `empty` | The system has no objects | Explain how an object will appear or be created |
| `filtered_empty` | Objects exist outside current filters | Show active filters and a clear-all action |
| `error` | The affected surface cannot resolve | Name the affected surface and provide safe retry |
| `success` | A completed transient outcome | Use Toast; do not move the working surface |
| `disabled` | Action is intentionally unavailable | Explain why and how to make it available |
| `pending` | Background work is not finished | Show row/task status; never present as success |

Page-blocking error is reserved for failure of the primary page task. A failed
audit summary, test request, or secondary chart remains local to that section.

## 8. Action Risk Model

Every mutation trigger must declare one of three risk classes.

### 8.1 `routine`

Examples: refresh, copy, filter, inspect, test when the test is read-only.

- no confirmation;
- success via Toast or row status;
- failure local to the affected surface.

### 8.2 `governed`

Examples: change package, save provider connection, save service configuration,
approve a trial, create an account.

- contextual drawer or dialog;
- show the target object and relevant before/after values;
- preserve the backend audit receipt;
- refresh only the affected object.

### 8.3 `destructive`

Examples: suspend an account, cancel a subscription, delete a connection,
disable a user, signed credit adjustment with negative effect.

- never the default primary action;
- require an explicit confirmation naming the object and impact;
- collect a reason when the API/audit contract supports it;
- state reversibility and user/service impact;
- preserve the backend audit receipt.

## 9. Responsive Contract

Desktop tables remain valid for comparison-heavy work, but mobile must not
require horizontal scrolling to complete the core task.

- Queue rows expose identity, status, reason, and next action in a narrow
  summary view.
- Secondary columns may remain in a focusable horizontal region.
- The first column and primary action remain discoverable.
- Drawers become full-screen panels below the desktop breakpoint.
- Toolbars stack in the order: view, search, filters, create/action.
- Touch targets are at least 44 CSS pixels for primary mobile controls.

## 10. Accessibility Contract

- Every input, select, textarea, and icon-only button has an accessible name.
- Selected, focused, disabled, and loading states remain visually distinct.
- Dialog focus is contained and returns to the meaningful trigger on close.
- Tables use headers and focusable labelled scroll regions when they overflow.
- Status is not expressed by color alone.
- Success uses a polite status region; blocking failure uses an alert region.
- Keyboard-only operators can complete every core task.

## 11. Data And Performance Contract

- Initial list payloads contain visible rows and summary counts, not full edit
  candidates or complete audit history.
- Candidate models, audit events, raw evidence, and inspector detail load on
  demand.
- A route must not issue duplicate production fetches for the same initial
  resource.
- Mutation refreshes are scoped to the affected row or object when practical.
- A loading state appears immediately when a route or inspector waits on data.
- Performance acceptance records initial request count, largest JSON payload,
  and time to primary working surface for the three pilot routes.

## 12. Component Ownership

Page files compose the route. They should not continue accumulating data
normalization, mutations, dialogs, tables, and several thousand lines of JSX.

After a pilot layout is accepted, split by responsibility:

- route data hook and normalized view model;
- page header and metric strip;
- toolbar and URL-backed filters;
- table/list or detail tabs;
- inspector/drawer;
- mutation dialog;
- loading/empty/error states;
- audit receipt entry.

Do not extract components before the target interaction is stable merely to
move lines between files.

## 13. Scientific Acceptance Metrics

### 13.1 Task efficiency

- A high-frequency task reaches its execution surface in at most three actions.
- The first viewport identifies state and next action without reading advanced
  evidence.
- Returning from detail preserves list filters and pagination.

### 13.2 Information hierarchy

- No more than five default summary metrics.
- No more than one primary action per section by default.
- Core working content appears within the first two desktop viewports.
- Low-frequency evidence is collapsed or contextual.

### 13.3 Safety and feedback

- Every destructive operation has object-specific confirmation.
- Every governed mutation that returns a receipt keeps it reachable.
- Success feedback never shifts the table or main working surface.
- A failed mutation preserves entered values and the surrounding page.

### 13.4 Accessibility and responsive behavior

- No unnamed form controls on the tested route.
- Core tasks work with keyboard only.
- Core mobile tasks do not depend on horizontal scrolling.
- Light and dark modes preserve the same information hierarchy.

### 13.5 Performance

- Pilot routes record and compare request count, payload size, and time to
  primary working surface before and after migration.
- Low-frequency resources are not fetched until their entry surface opens.

## 14. Phased Migration

### Phase A: architecture contract

- land this IA contract and its decision record;
- keep a complete route-to-model matrix;
- add a contract test that fails when a route is not classified;
- preserve the feedback/layout v1 contract.

### Phase B: three representative pilots

1. Customer detail: `detail` plus governed/destructive actions.
2. Service queue: `queue` plus filters, prioritization, and inspector.
3. Service settings: `configuration` plus dirty state, validation, test, save.

Each pilot must pass desktop/mobile, light/dark, state, keyboard, mutation, and
performance acceptance before its pattern is copied.

### Phase C: route migration by model

- migrate remaining queue routes;
- migrate remaining detail routes;
- migrate package, credit, provider, and routing configuration;
- migrate diagnostics into the shared diagnostic frame.

### Phase D: component and data-boundary extraction

- split accepted pilot patterns into shared primitives and route modules;
- remove duplicate fetch, state, feedback, and table implementations;
- keep route files as composition layers.

### Phase E: full acceptance

- execute the complete route matrix at desktop and narrow mobile widths;
- verify light and dark themes;
- verify all required states;
- verify keyboard and focus behavior;
- record request and payload evidence;
- run type, lint, i18n, contract, boundary, and repository fast gates.

## 15. Migration Rules

- Do not change route paths and page composition in the same step unless the
  old route redirects safely and tests cover it.
- Do not merge APIs or data truth merely because two routes share a workspace.
- Do not move local WordPress ownership into Cloud while consolidating UI.
- Preserve unrelated filters, scroll position, and form values after mutations.
- Every migrated route adds or updates a page-model contract test.
- A page is not complete because it looks consistent; it is complete only when
  its functional acceptance evidence is recorded.

## 16. Required Gates

For each migrated route, run the narrowest applicable set and record exact
results:

```bash
pnpm --dir frontend run type-check
pnpm --dir frontend run lint
pnpm --dir frontend run test:i18n-contract
pnpm --dir frontend run test:contracts
pnpm run check:fast
```

Also inspect the route at desktop and narrow mobile widths in light and dark
mode. Mutation tests must use safe fixtures and must not operate on unintended
customer or production records.

## 17. Completion Definition

The admin refactor is complete only when:

- every route in the matrix uses its declared page model;
- all three pilots have recorded acceptance evidence;
- remaining routes have migrated by model rather than by ad hoc styling;
- destructive and governed actions follow the risk model;
- all required UI states are distinguishable;
- mobile and keyboard core tasks are verified;
- large route files have been split after interaction stabilization;
- performance evidence shows low-frequency data is loaded on demand;
- Cloud/WordPress ownership boundaries remain unchanged;
- all required gates pass.
