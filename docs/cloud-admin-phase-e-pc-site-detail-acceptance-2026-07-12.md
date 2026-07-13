# Cloud Admin Phase E — PC Site Detail Acceptance

Date: 2026-07-12

## Scope

This checkpoint covers the desktop operator experience for `/admin/sites/[siteId]` only. Mobile and tablet refinement is deferred; existing responsive behavior remains outside this acceptance gate.

## Operator hierarchy

- The first screen presents one site posture conclusion and one primary next action.
- Account and current subscription remain contextual related surfaces; the account action is not duplicated in the page header.
- Runtime explanation is localized before it reaches the default operator surface.
- Audit follow-up stays collapsed and the raw audit API is not promoted as a primary page action.
- Commercial coverage, runtime inspection, usage, billing reconciliation, and workspace evidence are grouped under one collapsed advanced-evidence disclosure.
- The page no longer adds a second unscoped subscriptions-directory link beside the persistent navigation destination.

## Verification

- `node tests/unit/admin-site-detail-pc-v2-contract.mjs`
- `pnpm exec eslint 'src/app/admin/sites/[siteId]/page.tsx' src/lib/admin-commercial-copy.ts tests/e2e/admin-site-detail-pc-v2.spec.ts`
- `pnpm run type-check`
- `pnpm exec playwright test tests/e2e/admin-site-detail-pc-v2.spec.ts`

Result: static contract, lint, type-check, and the dedicated 1440 x 1050 desktop flow passed.

## Boundary check

The page continues to display hosted runtime, entitlement, usage, billing, and audit evidence only. It does not become a WordPress write owner, approval truth, local registry, or workflow control plane.
