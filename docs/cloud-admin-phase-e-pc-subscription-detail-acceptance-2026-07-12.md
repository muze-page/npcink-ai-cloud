# Cloud Admin Phase E — PC Subscription Detail Acceptance

Date: 2026-07-12

## Scope

This checkpoint covers the desktop operator experience for `/admin/subscriptions/[subscriptionId]`. Mobile and tablet refinement remains deferred.

## Operator hierarchy

- The first screen derives one conclusion from billing-statistics freshness, budget pressure, subscription lifecycle, and grace posture.
- The page exposes one primary next action: reconcile billing statistics when stale or missing; otherwise move to bounded customer coverage follow-up.
- Header-level back, customer, and package actions no longer compete with the current follow-up.
- Service state, billing-statistics freshness, and budget pressure form one compact follow-up focus.
- Package, usage, related sites, commercial interpretation, billing detail, and audit evidence are grouped under one collapsed advanced-evidence disclosure.
- Known backend commercial guidance is localized before display.
- Initial read failure preserves the admin route shell and retries the bounded request without a full application reload.

## Verification

- `node tests/unit/admin-subscription-detail-pc-v2-contract.mjs`
- `pnpm exec eslint 'src/app/admin/subscriptions/[subscriptionId]/page.tsx' src/lib/admin-commercial-copy.ts tests/e2e/admin-subscription-detail-pc-v2.spec.ts`
- `pnpm run type-check`
- `pnpm exec playwright test tests/e2e/admin-subscription-detail-pc-v2.spec.ts`

Result: static contract, lint, type-check, 1440 x 1050 desktop flow, advanced-evidence disclosure, and failure/retry flow passed.

## Boundary check

The surface remains a hosted commercial evidence and follow-up view. It does not create checkout, payment, entitlement, WordPress write, approval, local registry, or runtime-control authority.
