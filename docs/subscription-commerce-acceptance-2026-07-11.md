# Subscription Commerce Acceptance - 2026-07-11

Status: pre-production acceptance passed.

## Scope

This evidence covers the `0058` subscription-commerce release candidate on
branch `codex/subscription-commerce-rc`:

- backend commit: `487193ac6fa12c2e2c9cb47db2666d00537bb12e`
- Portal/Admin commit: `e631cccb6b2e0296052697ad68a50e5582db435e`
- Free, Plus, Pro, and account-bound Agency package transitions
- one shared 14-day paid-package trial
- payment callback, renewal, upgrade, scheduled downgrade, and refund state
  transitions

This document does not claim a real Alipay transaction or production `0058`
deployment. Those remain separate release gates.

## Commercial State Matrix

| Scenario | Expected result | Evidence |
| --- | --- | --- |
| Free to Plus | Plus activates for 30 days after verified payment | domain and Portal API tests passed |
| Plus to Pro | positive remaining-period price difference is charged; period end is preserved | domain tests passed |
| Pro renewal | 30 days are appended to the paid period | domain tests passed |
| Pro to Plus | paid Plus coverage is scheduled for the current period end | domain tests passed |
| paid tier to Free | Free is scheduled for the current period end | domain tests passed |
| Agency purchase | only the quoted account can purchase the active quote | domain and Portal API tests passed |
| shared trial | Plus may move to Pro or approved Agency without resetting the original 14-day end | domain and Portal API tests passed |
| trial abuse prevention | account, principal, and site-domain reuse cannot create a second paid trial | domain tests passed |
| expired checkout | unpaid orders expire after 24 hours and do not block a replacement order | domain tests passed |
| callback replay | repeated payment confirmation does not duplicate subscription activation | payment tests passed |
| partial refunds | cumulative successful refunds revoke coverage when they reach the full paid amount | domain tests passed |
| refund ordering | an earlier package order cannot be refunded over a later live order | domain tests passed |
| trial conversion refund | a full refund before trial end restores the original trial instead of paid coverage | domain tests passed |

## Automated Gates

- `pnpm run check:fast`
  - contract: `70 passed, 1 skipped`
  - domain: `164 passed, 3 skipped`
- `pnpm run check:seam`
  - API: `475 passed`
  - perimeter: `9 passed`
- `pnpm run lint`: Ruff and Mypy passed (`204` source files checked by Mypy)
- `pnpm run check:anti-drift`: passed
- `pnpm run check:release-policy`: passed
- frontend TypeScript and ESLint: passed
- admin/Portal i18n completeness: passed (`1643` keys)
- Portal workspace E2E: `7 passed`
- Admin operator E2E: `7 passed`

The only test warning was the existing Starlette `TestClient` deprecation
warning for the current `httpx` integration.

## PostgreSQL Migration Drill

An isolated temporary PostgreSQL database completed:

1. fresh migration chain to `20260710_0058`;
2. downgrade from `0058` to `0057`;
3. re-upgrade from `0057` to `0058`;
4. verification of `plan_offers`, `subscription_orders`, and `trial_claims`;
5. verification of the three `scheduled_*` account-subscription columns;
6. cleanup of the temporary database.

Result: passed and removed.

## Remaining Production Gates

- complete formal release smoke with all required production smoke secrets;
- create and checksum-verify a pre-deploy production backup;
- promote the reviewed release through `master` to `production`;
- verify production migration `20260710_0058` and the new tables;
- complete one real low-value Plus payment, Plus-to-Pro upgrade, and controlled
  full refund;
- create a post-deploy `0058` backup and restore it into an isolated database.
