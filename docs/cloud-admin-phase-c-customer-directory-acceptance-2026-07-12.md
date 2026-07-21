# Cloud Admin Phase C Customer Directory Acceptance - 2026-07-12

Status: accepted for the `/admin/accounts` module.

Route: `/admin/accounts`.

Page model: `queue + inspector`.

Fixture inspected: the local development frontend with disposable Playwright
admin-session and customer fixtures.

No live customer, site, subscription, package, billing, payment, entitlement,
credential, or WordPress mutation was executed during verification.

## Baseline Problems

- A wide horizontal table made customer comparison and narrow-screen use
  difficult.
- Search input changes immediately issued requests instead of allowing an
  operator to finish a query.
- Filters, pagination, and the selected customer were not durable in the URL.
- Development Strict Mode could issue duplicate initial reads.
- A failed refresh replaced the working surface instead of retaining the last
  usable customer records.
- Risk presentation did not fully account for explicit coverage follow-up.
- Customer creation, customer scanning, and record navigation competed inside
  one large surface.
- The list had no persistent customer focus or bounded related-surface context.

## Implemented Structure

- Compact operating header with Add customer as the primary action and Refresh
  as the secondary action.
- Compact current-page summary for critical, warning, monitor, stable, and
  refresh time.
- Server-backed global risk ordering before pagination.
- URL-backed search, status, expiry, coverage, package, plan, internal-record,
  sort, pagination-offset, and inspector-focus state.
- Explicit Apply for text/date fields to avoid requests on every keystroke.
- Responsive customer task list with one Inspect action and one primary Details
  action per record.
- Sticky desktop inspector that moves below the queue on narrow screens.
- A separate, explicitly opened customer-creation panel; the existing formal
  Free-package default remains intact.
- Failed refresh keeps the last successful records and labels retained results
  when they no longer match newly requested filters.
- Request sequencing prevents Strict Mode duplicate reads and stale responses
  from replacing newer results.

## Truth And Scope

- Customer, site, subscription, coverage, package, expiry, total, and
  pagination values are service-API results.
- Risk order is computed by the Cloud commercial service layer across the full
  filtered population before pagination.
- The page summary is explicitly current-page evidence, not a global risk
  dashboard.
- Customer creation remains an auditable Cloud service-plane operation and does
  not create payment, entitlement, or WordPress control-plane truth.

## Browser Evidence

### Desktop light

- Viewport: `1280 x 720` CSS pixels.
- Three fixture customers rendered in service-risk order: suspended, coverage
  follow-up, then stable.
- Queue and inspector rendered side by side.
- Document width remained exactly `1280` pixels, with no table or internal
  horizontal scroll surface.

### Desktop dark

- Dark root state was active.
- Body background resolved to `rgb(7, 17, 31)`.
- Document width remained exactly `1280` pixels and severity hierarchy remained
  visible.

### Narrow light

- Viewport: `390 x 844` CSS pixels.
- Document width remained exactly `390` pixels.
- The queue preceded the inspector in document order.
- No table or horizontal overflow appeared.

## Request And Failure Evidence

- Instrumented initial navigation issued one customer-list request.
- Search, coverage, sort, and inspector focus survived reload through the URL.
- Keyboard activation of Inspect selected the intended customer.
- A forced `503` after changing filters retained the previous customer result
  and showed the explicit last-successful-page warning.
- Customer creation produced a global success notification and refreshed the
  queue while preserving the formal Free-package default.

## Automated Evidence

- `admin_accounts_queue_v2_contract`: passed.
- `admin-accounts-queue-v2.spec.ts`: passed (`2` tests).
- Combined customer and operator E2E regression: passed (`11` tests).
- Focused customer-domain tests: passed (`4` tests).
- Targeted Ruff: passed.
- Targeted Mypy: passed.
- Targeted ESLint: passed.
- TypeScript type-check: passed.
- Full frontend contract suite: passed (`1812` translation keys).
- Full frontend i18n contract suite: passed.
- Repository `check:fast`: passed (`70` contract tests passed, `1` skipped;
  `192` domain tests passed, `3` skipped).

## Boundary Result

The customer directory reads and creates existing Cloud commercial
service-plane records and opens existing customer, service-status, Portal-user,
and subscription surfaces. It adds no checkout, payment provider, entitlement
truth, package truth, WordPress write, approval, ability, workflow, prompt,
router, MCP, or OpenClaw ownership.
