# Cloud Admin Phase C Support Request Queue Acceptance - 2026-07-12

Status: accepted for the `/admin/support-requests` module.

Route: `/admin/support-requests`.

Page model: `queue + inspector`.

Fixture inspected: the local development frontend with disposable Playwright
admin-session and support-request fixtures.

No live ticket reply, status update, attachment, customer, subscription,
payment, entitlement, credential, or WordPress mutation was executed during
visual verification.

## Baseline Problems

- Every ticket expanded its own status editor, internal-note editor, save
  action, and detail action.
- Customer-submitted content and internal handling controls competed at the
  same visual level.
- Search issued a request on every keystroke.
- Filters, pagination, and the selected ticket were not durable in the URL.
- Development Strict Mode could issue duplicate initial reads.
- A failed refresh replaced the working surface instead of preserving usable
  tickets.
- The page did not distinguish service-backed filtering/pagination from local
  current-page priority ordering.
- Saving a ticket could move the inspector to a different record after risk
  order changed.

## Implemented Structure

- Compact operating header with Refresh as the page action.
- Compact summary for globally reported open/in-progress totals, current-page
  overdue count, filtered total, and refresh time.
- URL-backed status, topic, query, current-page sort, pagination offset, and
  inspector focus.
- Explicit Apply for search to avoid a request on every keystroke.
- Responsive task list with one Inspect action and one primary detail action.
- Sticky desktop inspector that moves below the queue on narrow screens.
- Customer submission is read-only and visually separated from internal
  handling.
- Exactly one status and internal-note editor exists in the inspector instead
  of one editor per ticket row.
- Successful updates pin the current ticket in the URL before refreshing, so
  risk reordering cannot move the operator to another ticket.
- Failed filter loads retain and explicitly label the last successful page.
- Request sequencing prevents Strict Mode duplicate reads and stale responses
  from replacing newer results.

## Truth And Scope

- Status, topic, query, pagination, open count, and in-progress count are
  service-API results.
- Risk ordering is explicitly a current-page operation. It is not presented as
  global SLA truth.
- The existing four-state contract remains unchanged: open, in progress,
  resolved, and closed. No unsupported waiting-customer state was invented.
- Public replies, attachments, customer notifications, and the complete
  timeline remain in ticket detail.

## Browser Evidence

### Desktop light

- Viewport: `1280 x 720` CSS pixels.
- Four fixture tickets rendered in overdue, awaiting-response, in-progress,
  then complete order.
- Queue and inspector rendered side by side.
- Document width remained exactly `1280` pixels.
- A visual check found and corrected a premature four-column filter breakpoint;
  the final layout uses two stable filter columns at this viewport.
- One internal-note editor rendered for the selected ticket.

### Desktop dark

- Dark root state was active.
- Body background resolved to `rgb(7, 17, 31)`.
- Document width remained exactly `1280` pixels and ticket severity remained
  scannable.

### Narrow light

- Viewport: `390 x 844` CSS pixels.
- Document width remained exactly `390` pixels.
- The queue preceded the inspector in document order.
- No table or horizontal overflow appeared.

## Request And Failure Evidence

- Instrumented initial navigation issued one ticket-list request.
- Status, search, and inspector focus survived reload through the URL.
- Keyboard activation of Inspect selected the intended ticket.
- A forced `503` after changing search retained the previous ticket result and
  showed the explicit last-successful-page warning.
- A mocked status-and-note update showed global success feedback, refreshed the
  queue, and retained the updated ticket as inspector focus.

## Automated Evidence

- `admin_support_requests_queue_v2_contract`: passed.
- Existing support-request and admin-usability contracts: passed.
- `admin-support-requests-queue-v2.spec.ts`: passed (`2` tests).
- Combined support-request and operator E2E regression: passed (`11` tests).
- Targeted ESLint: passed.
- TypeScript type-check: passed.
- Full frontend contract suite: passed (`1812` translation keys).
- Full frontend i18n contract suite: passed.
- Repository `check:fast`: passed (`70` contract tests passed, `1` skipped;
  `192` domain tests passed, `3` skipped).

## Boundary Result

The queue reads and updates existing Cloud support service-plane records. It
adds no checkout, payment provider, entitlement truth, package truth,
WordPress write, approval, ability, workflow, prompt, router, MCP, or OpenClaw
ownership.
