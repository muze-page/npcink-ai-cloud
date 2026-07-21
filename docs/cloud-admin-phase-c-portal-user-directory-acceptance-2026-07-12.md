# Cloud Admin Phase C Portal User Directory Acceptance - 2026-07-12

Status: accepted for the `/admin/portal-users` module.

Route: `/admin/portal-users`.

Page model: `queue + inspector`.

Fixture inspected: the local development frontend with disposable Playwright
admin-session, user-directory, audit, and mutation fixtures.

No live Portal user, customer, membership, session, QQ binding, subscription,
payment, entitlement, credential, or WordPress mutation was executed during
verification.

## Baseline Problems

- The 880-line page placed filters, a wide table, per-row audit and disable
  controls, a permanent batch-disable toolbar, audit detail, and receipts in
  one default surface.
- Search and package fields issued requests on every keystroke.
- Filters, pagination, and the inspected user were not durable in the URL.
- Development Strict Mode could issue duplicate initial reads.
- A failed refresh replaced the working directory instead of preserving usable
  user records.
- Identity, membership, account, site, subscription, login, and QQ states were
  split across table columns, forcing operators to mentally reconstruct access
  health.
- The route was intentionally secondary navigation, but its breadcrumb fell
  back incorrectly to Overview.

## Implemented Structure

- Compact operating header with Refresh and a conditional latest-operation
  entry.
- Compact summary for active, disabled, current-page access issues,
  current-page awaiting-login users, and refresh time.
- URL-backed query, status, package, QQ, current-page sort, pagination offset,
  and inspector focus.
- Explicit Apply for search/package/QQ filters.
- Responsive directory list with one Inspect action per user.
- Sticky desktop inspector that moves below the directory on narrow screens.
- Access health combines identity, membership, account, site, subscription,
  and login evidence into four honest states: access issue, awaiting login,
  active access, and disabled.
- Audit, existing customer/site links, technical identifiers, and disable
  controls are placed in the current-user inspector.
- Single-user disable is behind an explicit Access actions disclosure.
- Batch disable appears only after one or more active users are selected.
- Durable mutation receipts use the compact latest-operation dialog; transient
  success uses global Toast feedback.
- Failed filter loads retain and explicitly label the last successful page.
- Request sequencing prevents duplicate initial reads and stale replacement.
- The secondary route now has an accurate Portal Users breadcrumb without
  returning to the top-level sidebar.

## Truth And Scope

- Query, status, package, QQ, pagination, active, disabled, and bound totals are
  service-API results.
- Access-risk ordering is explicitly a current-page operation, not a global
  identity-health claim.
- The directory only uses the frozen external `user` identity semantics. It
  introduces no additional role or permission vocabulary.
- Disable continues to revoke Cloud Portal sessions, memberships, and QQ
  bindings through the existing audited service endpoint. It does not delete a
  customer or WordPress user and no restore action was added.

## Browser Evidence

### Desktop light

- Viewport: `1280 x 720` CSS pixels.
- Four fixture users rendered in access-issue, awaiting-login, active, then
  disabled order.
- Directory and inspector rendered side by side.
- Document width remained exactly `1280` pixels.
- No table or horizontal-scroll surface rendered.
- Destructive disable remained behind Access actions.

### Desktop dark

- Dark root state was active.
- Body background resolved to `rgb(7, 17, 31)`.
- Document width remained exactly `1280` pixels and access severity remained
  scannable.
- The corrected breadcrumb displayed Self-registered users instead of
  Overview.

### Narrow light

- Viewport: `390 x 844` CSS pixels.
- Document width remained exactly `390` pixels.
- Low-frequency QQ and sort fields moved behind More filters.
- The first directory item began at `800` CSS pixels and therefore entered the
  initial viewport.
- The directory preceded the inspector in document order.

## Request, Mutation, And Failure Evidence

- Instrumented initial navigation issued one list request.
- Status, search, and inspector focus survived reload through the URL.
- Keyboard activation of Inspect selected the intended user.
- A forced `503` after changing search retained the prior record and displayed
  the explicit last-successful-page warning.
- Audit loaded through the principal-scoped audit endpoint.
- A mocked disable required confirmation, kept the user focused, updated the
  disabled state, displayed Toast success, and exposed the durable latest
  operation receipt.

## Automated Evidence

- `admin_portal_users_directory_v2_contract`: passed.
- Existing Portal-user and mutation-receipt contracts: passed.
- `admin-portal-users-directory-v2.spec.ts`: passed (`2` tests).
- Combined Portal-user and operator E2E regression: passed (`11` tests).
- Targeted ESLint: passed.
- TypeScript type-check: passed.
- Full frontend contract suite: passed (`1845` translation keys).
- Full frontend i18n contract suite: passed.
- Repository `check:fast`: passed (`70` contract tests passed, `1` skipped;
  `192` domain tests passed, `3` skipped).

## Boundary Result

The directory reads and updates the existing Cloud external-user service plane
and opens existing customer, site, and audit surfaces. It adds no role or
permission registry, checkout, payment provider, entitlement truth, package
truth, WordPress user/write, approval, ability, workflow, prompt, router, MCP,
or OpenClaw ownership.
