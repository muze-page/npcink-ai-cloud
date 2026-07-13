# Cloud Admin Service Queue Pilot Acceptance - 2026-07-12

Status: accepted.

Route: `/admin/coverage`.

Page model: `queue`.

Fixture inspected: the current local development service queue plus the
disposable Playwright admin operator fixture.

No customer, subscription, package, site, key, billing, or WordPress mutation
was executed during live verification.

## Implemented Structure

- Compact `Service risk queue` title with one primary Refresh action.
- Compact summary strip for needs-action, error, warning, aligned, and
  generated-time state.
- Stable toolbar with status tabs, customer/account/subscription/package
  search, reason filter, priority sort, and clear action.
- Filter, sort, and selected-inspector state stored in the route query string.
- Responsive task list instead of a desktop-width table.
- Explicit Inspect action selects the right-side customer inspector.
- One primary row action opens the bounded account, subscription, or site
  follow-up returned by the existing service queue API.
- Reason distribution and related low-frequency entry points are collapsed in
  the inspector.
- A failed refresh keeps the current queue, filters, and inspector usable.

## Browser Evidence

### Desktop light

- Viewport: `1280 x 720` CSS pixels.
- Queue and inspector rendered side by side without document overflow.
- Toolbar used a two-column control layout inside the available queue width.
- Row actions remained fully visible after replacing the four-column table.

### Desktop dark

- Viewport: `1280 x 720` CSS pixels.
- `dark` root state was active.
- Queue row and inspector remained visible with no document overflow.

### Narrow light and dark

- Viewport: `390 x 844` CSS pixels.
- No document horizontal overflow.
- No table element or 1024-pixel internal scroll surface remained.
- Queue item exposed both Inspect and its primary follow-up action.
- Inspector width remained inside the mobile content column.
- Dark mode resolved the body background to `rgb(7, 17, 31)` without changing
  the information hierarchy.

### Filter and inspector persistence

- Live status `All` and `Customer name` sort produced
  `?status=all&sort=customer`.
- Reload retained the pressed All state and selected sort.
- Selecting the second live row changed the inspector from the aligned
  `acct_site_npcink_local` customer to the warning
  `acct_magick_ai_local` customer.
- The selected focus was stored as
  `focus=acct_magick_ai_local%3Abilling_snapshot_follow_up`.

## Request and Performance Evidence

Development-mode uncached reload sampling:

- Before: 2 duplicate `/api/admin/coverage-work-queue` responses, 20,640
  encoded bytes total.
- After: 1 `/api/admin/coverage-work-queue` response, 10,320 encoded bytes.
- Successful response headers completed in about 39 ms in the sampled request.
- The resource response ended at about 726 ms in the sampled navigation and
  the primary queue heading was visible.
- No additional account, subscription, plan, or site detail request is made on
  the default queue surface.

## Automated Evidence

- `admin_coverage_workspace_contract`: passed.
- `admin-service-queue-v2.spec.ts`: passed.
- Existing focused admin coverage E2E smoke: passed.
- TypeScript type-check: passed.
- Targeted ESLint: passed.
- Full frontend i18n and contract suites: passed (`1774` translation keys).
- Repository `check:fast`: passed (`70` contract tests passed, `1` skipped;
  `191` domain tests passed, `3` skipped).

The focused E2E test verifies:

- default prioritization and all-status expansion;
- search, reason filter, and customer-name sort;
- keyboard selection of the inspector;
- query-string persistence across reload;
- refresh failure preserving current queue and filters;
- no mobile horizontal overflow.

## Boundary Result

The queue reads the existing Cloud service-plane coverage projection and only
opens existing customer, subscription, site, and package surfaces. It adds no
checkout, payment, entitlement truth, WordPress write, approval, ability,
workflow, prompt, router, MCP, or OpenClaw ownership.
