# PC Launch Readiness - 2026-07-10

Status: production-deployed PC launch candidate; controlled production
validation complete.

## Scope

This pass prioritizes the PC admin and Portal paths required for an early
commercial launch. Mobile layout polish and an operator identity are deferred.
The only product identities in scope are `platform_admin` and Portal `user`.

Cloud remains the hosted runtime and service-detail layer. WordPress approval,
router truth, and final writes remain local.

## Production State

- Production application release commit:
  `c5fdfe7a91b74c4bbc81564e9d5088102b53abde`.
- Release evidence may be updated on `master` after deployment; a docs-only
  difference does not indicate an unpromoted application change.
- Production database migration: `20260710_0057 (head)`.
- The obsolete `site_user_grants` table is absent.
- All 11 production services are running; the public health endpoint reports
  `healthy`.
- Dependabot has no open security alerts.

## Verified Product Paths

- Admin package catalog exposes Free, Plus, Pro, and Agency in that order; all
  four production plans are active.
- Admin credit packs use CNY pricing and a 365-day validity period.
- Portal billing exposes Plus between Free and Pro and shows purchasable credit
  packs with one-year validity.
- Account, provider, service-settings, SMTP preview, and Alipay configuration
  surfaces load on a 1280px PC viewport without page-level horizontal overflow.
- Portal and admin browser sessions cannot substitute for each other.
- Portal authorization uses `account_user_memberships` as its only truth.
- The Admin customer directory owns account/package/service operations;
  self-registered Portal users remain a secondary user-management surface.
- Service risk is a secondary route from service status rather than a separate
  primary navigation item.
- PC Addon binding preserves its full query through email-code login and returns
  the complete payload to WordPress in Playwright coverage.

## Verified Production Gates

- PRs `#146` and `#147` merged through repository protection.
- The hard cutover reached production through PR `#148`.
- The dependency security follow-up reached production through PRs `#149` and
  `#150`; Cloud CI and CodeQL passed.
- A verified database backup was created before the hard cutover.
- A fresh `0057` backup was restored successfully into an isolated temporary
  database on 2026-07-10. See
  [Production Backup Restore Drill - 2026-07-10](production-backup-restore-drill-2026-07-10.md).
- Production SMTP delivered three consecutive messages to a real mailbox.
- All three stored service settings remained readable after restart using the
  dedicated `NPCINK_CLOUD_SERVICE_SETTINGS_SECRET`; the retired key fallbacks
  could not decrypt them.
- A real signed runtime smoke covered catalog, execution, run/result, stats,
  usage, health, and perimeter paths. Temporary smoke keys were revoked.
- Production release run `29084936244` completed successfully in `9m41s`;
  deployment took `4m07s` and post-production smoke took `15s`.
- Production plans and credit-pack catalog were verified as CNY commercial
  data, including Plus and the 365-day credit validity policy.

## Remaining Launch Operations

- Configure the formal release-smoke secrets and run the complete
  `deploy/release-smoke.sh` path. The production workflow passed the public
  preflight but conditionally skipped formal Portal/Admin smoke because those
  secrets were not present; manual SMTP and signed-runtime evidence remain
  valid.
- Complete one real low-value Alipay transaction and verify paid-order credit
  grant, callback idempotency, amount/currency matching, and Portal display.
- Complete one real WordPress Addon reconnect before the first external user;
  the automated binding flow and signed runtime path are covered, but a fresh
  production plugin reconnect is still an operator action.
- Review the historical `alembic check` index and unique-constraint naming
  differences. The production database is at migration head; this is schema
  hygiene rather than a current runtime failure.
- Confirm traces are queryable in the configured production sink.
- Observe the release for 24 hours before declaring the PC launch generally
  available.
- QQ login remains optional. Configure and test it only if it is enabled for
  the initial launch.

## Rollback

1. Preserve `NPCINK_CLOUD_SERVICE_SETTINGS_SECRET` during any application
   rollback.
2. Redeploy the previous production release for an application-only regression.
3. Use the verified backup only for a confirmed data or schema incident; first
   restore into a separately named database and validate migration state and
   critical data before switching traffic.
4. Do not restore directly over the live production database while API or
   worker processes can write to it.
5. Rerun health, Portal login, provider runtime, payment callback, SMTP, cadence,
   and worker-heartbeat checks after rollback.
