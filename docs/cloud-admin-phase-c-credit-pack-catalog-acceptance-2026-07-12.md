# Cloud Admin Phase C Credit Pack Catalog Acceptance - 2026-07-12

Status: accepted for the `/admin/credit-packs` module.

Route: `/admin/credit-packs`.

Page model: `configuration directory + inspector + one-item editor`.

Evidence sources: the current local Cloud credit-pack catalog and disposable
Playwright fixtures. No live credit-pack, payment-order, credit grant,
subscription, entitlement, customer, or WordPress mutation was executed during
browser acceptance.

## Baseline Problems

- The default route rendered every pack as a long editable card and exposed
  `27` input controls for a three-pack catalog before the operator selected a
  task.
- Desktop cards read like a customer pricing grid rather than a bounded
  commercial configuration surface.
- The header-level Save action did not communicate which pack or values would
  change.
- Mobile stacked three metric cards before the catalog; the first editable pack
  began around `798` CSS pixels.
- Pack selection, active/inactive filtering, and editing context were not
  durable in the URL.
- Initial development reads were not explicitly deduplicated, and refresh
  failure did not explicitly label retained catalog data.

## Implemented Structure

- Compact page header with Refresh and an explicit return to Package Catalog.
- Compact summary pills for active count, default validity, human-readable
  expiry policy, and last load time.
- Read-first pack directory showing status, RMB amount, included credits, and
  recommended package tiers.
- URL-backed `status` and `focus` state.
- Desktop sticky inspector that follows the directory on narrow screens.
- The default page contains no editable inputs and no ambiguous Save-all
  action.
- Editing opens one selected pack in the shared accessible Modal.
- Save remains disabled until that pack changes.
- Saving replaces only the selected item in the client draft while preserving
  the complete atomic catalog PATCH payload required by the service.
- Successful saves use global Toast feedback; failed refresh retains and
  labels the last successful catalog.
- Request guards deduplicate Strict Mode reads and reject stale replacement.

## Truth And Boundary

- The existing credit-pack service response remains the catalog truth.
- `ADMIN_CURRENCY` keeps customer purchase pricing fixed to CNY.
- The backend still receives and validates the complete catalog atomically.
- Existing payment orders keep their purchase-time snapshot.
- The editor affects future purchases only; it does not create a wallet,
  permanent balance, package entitlement, subscription top-up, or WordPress
  control surface.

## Browser Evidence

### Current local catalog

- Three real local packs rendered with current labels, RMB amounts, included
  credits, validity, visibility, and tier recommendations.
- The default route rendered zero input controls.
- Opening the editor rendered only the selected pack fields; Save was disabled
  before any change.
- The editor was closed without submitting a live mutation.

### Desktop light and dark

- Viewport: `1280 x 720` CSS pixels.
- Directory and inspector rendered side by side at approximately `669px` and
  `311px` content widths.
- The first row began at approximately `397` CSS pixels.
- Both themes retained clear selected, active, amount, and action hierarchy.
- Document width remained exactly `1280` CSS pixels.

### Narrow light

- Viewport: `390 x 844` CSS pixels.
- Document width remained exactly `390` CSS pixels.
- The first catalog row began at approximately `598` CSS pixels.
- Summary metrics wrapped as compact pills instead of stacked metric cards.
- The default page contained zero editable inputs and no horizontal overflow.

## Request And Mutation Evidence

- Instrumented initial navigation issued one catalog request.
- Focus and visibility filter survived through the URL and reload.
- A forced `503` refresh retained the current filtered pack directory and
  displayed a last-successful-catalog notice.
- Canceling the editor issued no PATCH request.
- The disposable save fixture issued one PATCH containing all three packs,
  changed only `pack_medium`, preserved `pack_small`, and updated the inspector
  after the response.

## Automated Evidence

- `admin_credit_packs_directory_v2_contract`: passed.
- Existing `admin_credit_packs_contract`: passed after replacing the obsolete
  editable-card-wall requirement with the accepted directory model.
- Full frontend contract suite: passed (`1890` translation keys covered).
- Full frontend i18n contract suite: passed.
- `admin-credit-packs-directory-v2.spec.ts`: passed (`2` tests).
- Combined credit-pack, package-catalog, and operator E2E regression: passed
  (`13` tests).
- TypeScript and targeted ESLint: passed.
- Repository `pnpm run check:fast`: passed (`70` contract tests passed,
  `1` skipped; `192` domain tests passed, `3` skipped).

## Boundary Result

The refactor changes task hierarchy, responsive layout, URL state, and edit
scope only. It adds no wallet, stored-balance ledger, permanent credit,
payment-provider truth, entitlement truth, WordPress write/control, approval,
ability, workflow, prompt, router, MCP, or OpenClaw ownership.
