# Cloud Admin Phase C Subscription Queue Acceptance - 2026-07-12

Status: accepted for the `/admin/subscriptions` module.

Route: `/admin/subscriptions`.

Page model: `queue`.

Fixture inspected: the local development frontend with disposable Playwright
admin-session and subscription fixtures.

No live subscription, customer, site, package, billing, payment, entitlement,
credential, or WordPress mutation was executed during verification.

## Baseline Problems

- The page used risk-queue copy but still behaved like a filtered record list.
- Applied filters did not persist in the URL.
- The development lifecycle could issue duplicate initial reads.
- Refresh failure replaced the whole working surface instead of preserving
  usable records.
- Risk priority did not place stale or missing billing statistics ahead of
  stable active subscriptions.
- Each row exposed customer, site, and detail navigation simultaneously.
- There was no persistent inspector focus or explicit current-record context.
- The four large metric cards described only the current page without a compact
  operational hierarchy.

## Implemented Structure

- Compact operating header with Refresh as the only primary page action.
- Compact current-page summary for critical, warning, monitor, stable, and
  refresh time.
- Server-backed status, account, package, expiry, offset, and pagination state.
- URL-backed filters, current-page sort, pagination offset, and inspector focus.
- Explicit Apply action for account/package/expiry fields to avoid a request on
  every keystroke.
- Current-page risk sorting that includes subscription lifecycle, billing
  snapshot freshness, and near-term expiry.
- Responsive task list with one Inspect action and one primary detail action.
- Sticky desktop inspector that moves below the queue on narrow screens.
- Failed refresh keeps the last successful records and filters usable.
- Failed loading after a filter change explicitly labels the displayed records
  as the last successful page instead of implying they match the new filter.
- Request sequencing prevents Strict Mode duplicate reads and stale responses
  from replacing newer results.

## Truth And Scope

- Status, account, package, expiry, total, and pagination are service-API
  results.
- Risk and expiry sorting are explicitly labelled as current-page operations.
- The page does not claim its 20-record page summary is a global risk count.
- Cross-account global service-risk prioritization remains owned by
  `/admin/coverage`.

## Browser Evidence

### Desktop light

- Viewport: `1280 x 720` CSS pixels.
- Three fixture subscriptions rendered in risk order: critical lifecycle,
  stale billing statistics, then stable service.
- Queue and inspector rendered side by side with zero document overflow.
- Each row exposed one inspector action and one primary detail action.

### Desktop dark

- Dark root state was active.
- Body background resolved to `rgb(7, 17, 31)`.
- Document overflow remained zero and severity hierarchy remained visible.

### Narrow dark

- Viewport: `390 x 844` CSS pixels.
- Document width remained exactly `390` pixels.
- Queue item width was `332` pixels and inspector width was `366` pixels.
- One filter form remained in the document and no internal horizontal scroll
  surface appeared.

## Request And Failure Evidence

- Instrumented initial navigation issued one subscription-list request.
- Status, account, package, sort, and focus survived reload through the URL.
- Keyboard activation of Inspect selected the intended subscription.
- A forced `503` refresh retained the visible queue and filter drafts.
- A forced `503` after changing filters retained the previous result and showed
  the explicit last-successful-page warning.

## Automated Evidence

- `admin_subscriptions_queue_v2_contract`: passed.
- `admin-subscriptions-queue-v2.spec.ts`: passed.
- Existing queue-page hierarchy regression for `/admin/subscriptions`: passed.
- Targeted ESLint: passed.
- TypeScript type-check: passed.
- Full frontend contract suite: passed (`1805` translation keys).
- Full frontend i18n contract suite: passed.
- Repository `check:fast`: passed (`70` contract tests passed, `1` skipped;
  `191` domain tests passed, `3` skipped).

The complete `admin-operator-path.spec.ts` now passes all `9` tests. Its stale
Overview and customer-detail assertions were reconciled with the accepted
task-oriented layouts, and the ambiguous subscription detail selector is now
scoped to the queue row rather than matching both the row and inspector. No
duplicate entry point or legacy combined operation surface was restored to make
the suite pass.

## Boundary Result

The queue reads existing Cloud commercial service-plane records and opens
existing subscription, customer, and site detail surfaces. It adds no checkout,
payment provider, entitlement truth, package truth, WordPress write, approval,
ability, workflow, prompt, router, MCP, or OpenClaw ownership.
