# Admin Customer Surface Consolidation History - 2026-06-30

Status: accepted implementation history.

Purpose: summarize the recent platform-admin customer surface cleanup so future
operators and AI agents can understand why the account, Portal user, service
follow-up, subscription, and package views are arranged the way they are.

This document records local project history. It does not introduce a new API,
a new identity type, a second WordPress control plane, or a new commercial
source of truth.

## Boundary

Npcink AI Cloud remains the hosted runtime and service-plane enhancement layer.
It may own customer account service state, package and subscription evidence,
usage and entitlement evidence, audit evidence, and bounded Admin/Portal
surfaces.

Cloud must not become:

- a WordPress write owner;
- a second ability registry;
- a second workflow registry;
- a prompt, preset, router, MCP, or OpenClaw source of truth;
- a replacement for local Core approval, preflight, or audit truth;
- a customer-facing raw runtime-key control plane.

The identity contract remains limited to:

- `platform_admin`: bounded Cloud operator/admin surface.
- `user`: bounded Portal member/account/site surface.

## What Was Consolidated

### Customer and Portal user navigation

`/admin/accounts` and `/admin/portal-users` are both customer-domain surfaces,
but they answer different operator questions:

- `/admin/accounts`: customer account register, package posture, sites,
  subscriptions, and detail entry.
- `/admin/portal-users`: self-registered Portal user principals and access
  risk controls.

The accepted direction was to keep both pages under one customer menu area and
separate them with tabs instead of top-level menu entries.

Current customer tab names:

- `Customer register` / `客户目录`
- `Registered users` / `注册用户`
- `Service follow-up` / `服务跟进`
- `Subscription records` / `订阅记录`

This keeps the top-level Admin navigation customer-first without hiding the
distinction between account records and login principals.

### Account register and service follow-up

`/admin/accounts` and `/admin/coverage` were also consolidated conceptually.
The account register should answer "who are the customers and what package/site
footprint do they have?" The service follow-up page should answer "which
customers need operator action now?"

Accepted direction:

- keep `/admin/accounts` as the customer directory;
- keep `/admin/coverage` as the service follow-up queue;
- link them with customer tabs and one explicit service-follow-up metric;
- avoid duplicated "open customer service status" buttons.

The account page now keeps four summary metrics:

- customers;
- sites;
- subscriptions;
- service follow-up.

The service-follow-up metric is a whole clickable tile. It replaces the earlier
small linked number and the redundant secondary button.

### Coverage page sub-tabs

`/admin/coverage` now uses a second-level tab control for two different
questions:

- `Follow-up queue` / `跟进队列`: current blockers and operator actions.
- `Package overview` / `套餐概览`: read-only package comparison.

The second-level tabs are intentionally compact. They should not look like
another top-level customer menu.

Package maintenance remains in `/admin/plans`. The package overview inside
service follow-up is read-only comparison context, not a second plan editor.

### Trial readiness removal

The old "trial readiness" block belonged to an earlier internal trial flow.
That operating path is now closed.

Accepted direction:

- remove the trial-readiness summary from account detail;
- do not keep trial preparation copy as a standing customer operation;
- use package, usage, sites, and checks tabs on account detail instead.

### Redundant related entries removal

Several related-entry panels and buttons were removed because the new tab
structure already provides the route:

- the account overview no longer shows a separate "open customer service
  status" button;
- the coverage queue no longer shows a default "related surfaces" panel;
- the coverage empty state only shows an account-register entry when the whole
  visible queue is empty.

The rule is: use a tab or a primary metric when it is the intended navigation
path, and avoid repeating the same destination as a separate card or button.

## Systemic Fixes Landed

### Visible queue counts

The coverage page used to risk mixing two scopes:

- summary numbers from the raw API queue;
- visible rows after hiding smoke, malformed, or internal records.

That could make the UI show a nonzero "needs action" count while the visible
queue was empty.

The accepted fix is to compute the displayed summary, filter pills, and reason
summary from the same visible queue item set used by the table.

### Copy and labels

The account page copy now describes the register honestly:

```text
Review customers, packages, site footprint, and subscription coverage. Service
follow-up stays in the service queue.
```

Chinese copy:

```text
查看客户、套餐、站点和订阅覆盖；服务跟进在服务队列中处理。
```

The table column previously labeled only `Sites` also showed subscription
counts. It is now labeled `Sites / subscriptions` / `站点 / 订阅`.

Filter labels now use localized admin copy:

- `Coverage state` / `覆盖状态`
- `Package type` / `套餐类型`
- `Advanced filters` / `高级筛选`
- `Covered` / `已覆盖`
- `Uncovered` / `未覆盖`

## Current Implemented Shape

Customer tab component:

- `frontend/src/components/admin/CustomerAdminTabs.tsx`

Customer register:

- `frontend/src/app/admin/accounts/page.tsx`
- Four summary metrics.
- Whole-card service follow-up entry.
- Localized coverage/package filters.
- `Sites / subscriptions` table header.
- No duplicated service-status button.

Service follow-up:

- `frontend/src/app/admin/coverage/page.tsx`
- Visible-queue-derived summary counts.
- Compact second-level tabs.
- No default related-surfaces card.
- Package overview remains read-only and points maintenance to `/admin/plans`.

Localization:

- `frontend/src/lib/i18n.ts`

Regression coverage:

- `frontend/tests/e2e/admin-operator-path.spec.ts`

## Verification Record

Commands run:

```bash
cd frontend && ./node_modules/.bin/eslint \
  src/components/admin/CustomerAdminTabs.tsx \
  src/app/admin/accounts/page.tsx \
  src/app/admin/coverage/page.tsx \
  tests/e2e/admin-operator-path.spec.ts
```

```bash
git diff --check -- \
  frontend/src/components/admin/CustomerAdminTabs.tsx \
  frontend/src/app/admin/accounts/page.tsx \
  frontend/src/app/admin/coverage/page.tsx \
  frontend/src/lib/i18n.ts \
  frontend/tests/e2e/admin-operator-path.spec.ts
```

```bash
pnpm run frontend:type-check
```

```bash
pnpm run frontend:test:e2e:admin-operator-path
```

Result:

- targeted ESLint passed;
- diff whitespace check passed;
- frontend type-check passed;
- admin operator Playwright path passed: 7 tests.

Real local page verification:

- `/admin/accounts` showed the new customer tabs, four metrics, localized
  labels, and no old duplicated service-status button.
- `/admin/coverage` showed matching visible counts between the top metric and
  filter pills.
- `/admin/coverage` showed compact `跟进队列 / 套餐概览` sub-tabs.
- desktop and 390px mobile viewport checks had no horizontal overflow.

## Deferred

Do not expand this area into a full CRM yet.

Defer until real operator volume proves the need:

- batch customer account operations;
- a full account audit timeline UI;
- destructive account deletion;
- package editing from the coverage overview;
- a mixed Admin/Portal shell;
- customer-facing checkout or billing front-office.

The next useful work should stay narrow: improve customer register filtering,
add clearer empty states only where operators get stuck, and keep package
maintenance centralized in the package catalog.
