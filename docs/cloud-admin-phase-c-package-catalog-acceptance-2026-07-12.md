# Cloud Admin Phase C Package Catalog Acceptance - 2026-07-12

Status: accepted for the `/admin/plans` module.

Route: `/admin/plans`.

Page model: `queue + inspector`.

Fixture inspected: the local development frontend with disposable Playwright
admin-session and package-catalog fixtures.

No live package, plan version, subscription, credit pack, payment, entitlement,
credential, customer, or WordPress mutation was executed during verification.

## Baseline Problems

- The default workspace used a hero metric surface followed by four large
  package cards, making the page read like a pricing comparison page rather
  than an operator catalog.
- Publication readiness, published-version counts, subscription use, limits,
  and maintenance entry points were distributed across multiple large blocks.
- Initial reads were not explicitly deduplicated under development Strict Mode.
- A refresh failure could replace the working catalog with a full loading or
  error state.
- The current package focus, readiness filter, search, and sort were not
  durable in the URL.
- Low-frequency package initialization and exceptional package creation shared
  too much visual weight with routine catalog scanning.

## Implemented Structure

- Compact operating header with Refresh and the existing credit-pack entry.
- Compact summary for managed packages, ready packages, attention items,
  active subscriptions, and refresh time.
- URL-backed package query, readiness state, current-page sort, and inspector
  focus.
- Explicit Apply for package search.
- Responsive standard-package list ordered by missing, unpublished, then ready
  by default.
- Sticky desktop inspector that moves below the directory on narrow screens.
- The inspector shows current plan/version status, published-version count,
  subscription use, site limit, included points, and currency.
- Existing package detail and filtered subscription queue remain the primary
  follow-up surfaces.
- Missing packages open Advanced setup instead of exposing creation controls in
  the default list.
- Standard-package initialization and exceptional plan creation remain inside
  the collapsed Advanced maintenance surface.
- Mutation success uses global Toast feedback.
- Failed refresh retains and labels the last successful catalog.
- Request sequencing prevents duplicate initial reads and stale replacement.

## Truth And Scope

- `plans + plan_versions` remain the only package execution truth.
- Free, Plus, Pro, and Agency remain the canonical presentation templates.
- Publication, limits, currency, subscription counts, and plan status come
  from the existing service response.
- Search, readiness filtering, and attention sorting operate on the four loaded
  canonical package templates and do not claim a separate registry.
- No package pricing, release, subscription, payment, or entitlement contract
  was changed.

## Browser Evidence

### Desktop light

- Viewport: `1280 x 720` CSS pixels.
- Four standard packages rendered in missing, missing, ready, then ready order.
- Directory and inspector rendered side by side.
- Document width remained exactly `1280` pixels.
- No main-surface package card grid rendered.
- Advanced maintenance was closed.

### Desktop dark

- Dark root state was active.
- Body background resolved to `rgb(7, 17, 31)`.
- Document width remained exactly `1280` pixels and readiness severity remained
  scannable.

### Narrow light

- Viewport: `390 x 844` CSS pixels.
- Document width remained exactly `390` pixels.
- The first package row began at `768` CSS pixels and entered the initial
  viewport.
- The directory preceded the inspector and Advanced maintenance remained
  collapsed.

## Request And Failure Evidence

- Instrumented initial navigation issued one catalog request.
- Readiness, search, and inspector focus survived reload through the URL.
- Keyboard activation of Inspect selected the intended package.
- A forced `503` refresh retained the filtered catalog and displayed the
  last-successful-catalog warning.
- Existing package detail links and plan-filtered subscription links remained
  connected.
- Advanced maintenance exposed initialization and exceptional creation only
  after an explicit disclosure action; no mutation was executed.

## Automated Evidence

- `admin_plans_directory_v2_contract`: passed.
- Existing package-pricing and admin-usability contracts: passed.
- Full frontend contract suite: passed, including bilingual completeness for
  `1870` translation keys.
- Full frontend i18n contract suite: passed.
- `admin-plans-directory-v2.spec.ts`: passed (`2` tests).
- Combined package and operator E2E regression: passed (`11` tests).
- Targeted ESLint: passed.
- TypeScript type-check: passed.
- Repository `pnpm run check:fast`: passed (`70` contract tests passed,
  `1` skipped; `192` domain tests passed, `3` skipped).

## Boundary Result

The catalog reads the existing Cloud commercial package and plan-version truth
and opens existing package, subscription, and credit-pack surfaces. It adds no
second package registry, checkout, payment provider, entitlement truth,
WordPress write/control, approval, ability, workflow, prompt, router, MCP, or
OpenClaw ownership.
