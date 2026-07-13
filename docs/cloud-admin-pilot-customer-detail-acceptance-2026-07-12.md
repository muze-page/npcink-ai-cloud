# Cloud Admin Customer Detail Pilot Acceptance - 2026-07-12

Status: accepted.

Route: `/admin/accounts/[accountId]`.

Page model: `detail`.

Fixture inspected: `acct_magick_ai_local` in the local development environment.

No customer, package, credit, account-status, or audit mutation was executed
during this read-only verification.

## Implemented Structure

- Default section: Overview.
- Commercial section: package changes and account-bound Agency quote/trial.
- Credits and usage section: current-period top-up, audited credit adjustment,
  quota posture, credit breakdown, ledger, and resource limits.
- Sites section: connected site footprint and detail entry.
- Audit section: account and commercial receipts, bounded account audit summary,
  and low-frequency per-site runtime checks.
- Account suspension/restore is behind an explicit “More account actions”
  disclosure and keeps object-specific confirmation.
- Transient account/commercial success uses global Toast.
- Durable receipts are not rendered in the default overview or commercial
  working surface.

## Read-Only Browser Evidence

### Desktop

- Five tabs rendered with Overview selected on initial load.
- Commercial tab showed `Package and Agency operations`.
- Commercial tab did not render top-up or credit-adjustment controls.
- Credits tab showed `Top-up and credit adjustment`, quota, ledger, and resource
  limit sections.
- Credits tab did not render package-change controls.
- Audit tab showed the bounded account audit summary and advanced site checks.
- No duplicate mutation receipt surface was rendered without a current receipt.

### Narrow Mobile

Viewport: `390 x 844` CSS pixels.

- Document horizontal overflow: false.
- Customer detail tab list width: 324 CSS pixels inside the content column.
- Tab controls stacked in a single-column grid.
- Header actions and account-state controls stayed inside the viewport.

### Theme

- Desktop light (`1280 x 720`): no horizontal overflow.
- Desktop dark (`1280 x 720`): `dark` root class applied and no horizontal
  overflow.
- Narrow dark (`390 x 844`): no horizontal overflow; tab list width 320 CSS
  pixels in the sampled layout.
- Narrow light (`390 x 844`): no horizontal overflow; tab list width 324 CSS
  pixels after a fresh navigation.
- The narrow theme control was exercised through the visible mobile menu.
- The explicit viewport override was reset after verification.

### State Handling

- The first account audit-summary check returned 404 while the rest of the
  customer page stayed usable and the panel exposed Retry.
- Diagnosis found that the admin catch-all proxy incorrectly added the
  `/admin` backend namespace to this bounded service-plane evidence read.
- The proxy now maps audit event list and summary reads to
  `/internal/service/audit-events...`; the live account summary returned 200
  after the fix.
- A local credit-adjustment validation check entered `123` credits without an
  operator reason and selected Apply.
- The validation remained contextual, issued no mutation request, and retained
  the entered `123` value so the operator could correct the missing reason.
- The temporary value was cleared after verification.

### Keyboard and Confirmation

- Opening the account-suspension confirmation moved focus into the dialog.
- `Shift+Tab` from the close control wrapped to the final confirmation action.
- `Tab` from the final confirmation action wrapped to the close control.
- `Escape` closed the dialog and returned focus to the originating Suspend
  account action.
- The final destructive action was not selected; the account remained active.

### Request and Performance Baseline

Development-mode browser sampling used the same local fixture and an uncached
page reload.

- Before tab-scoped loading: 12 admin API responses / about 244 KB in the
  captured window, including duplicated account, plan, quota, ledger, and site
  detail requests.
- After tab-scoped loading and request guards: 1 admin API response / 4,771
  bytes on the default Overview surface.
- Largest initial JSON response before the change: `/api/admin/plans`, 34,905
  bytes.
- Largest and only initial JSON response after the change:
  `/api/admin/accounts/acct_magick_ai_local`, 4,771 bytes.
- The account response completed at about 595 ms in the successful sampled
  navigation; the customer heading was visible when inspected.
- Commercial requested `/api/admin/plans` only when selected.
- Credits requested `quota-summary` and `credit-ledger` only when selected.
- Audit requested the two site-detail resources only when selected. Its audit
  summary request currently appears twice in React development Strict Mode and
  is retained as a follow-up performance detail rather than a default-surface
  blocker.

## Automated Evidence

- `pnpm --dir frontend run type-check`: passed.
- Targeted ESLint for customer detail and i18n: passed.
- `pnpm --dir frontend run test:i18n-contract`: passed.
- `pnpm --dir frontend run test:contracts`: passed.
- `admin_account_detail_v2_contract`: passed.
- `admin_information_architecture_v2_contract`: passed with 23 classified
  routes.
- `modal_keyboard_accessibility_contract`: passed.
- `admin-customer-detail-v2.spec.ts`: passed with mocked disposable operator
  state. It verified one confirmed package change and one audited credit
  adjustment, including their durable mutation receipts in Audit.
- The customer-detail segment of `admin-operator-path.spec.ts` was reconciled
  with the accepted five-tab task model and passed. The old assertion expected
  `Package and top-up` on the default page; the updated regression verifies that
  package operations are in Commercial, top-up operations are in Credits and
  usage, and the legacy combined surface is absent.
- After the Overview and subscription selector assertions were reconciled with
  their accepted task models, the complete `admin-operator-path.spec.ts` passed
  all `9` tests.

## Accepted Follow-up

The React development-only duplicate audit-summary request remains a bounded
performance follow-up. It does not affect the default working surface, the
production contract, or acceptance of this pilot.

## Boundary Result

The pilot changes only Cloud-owned account, commercial, credit, site-detail,
and audit presentation. It does not add WordPress writes, approval, workflow,
ability, prompt, router, MCP, or OpenClaw ownership.
