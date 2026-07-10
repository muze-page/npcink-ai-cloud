# PC Launch Readiness - 2026-07-10

Status: pre-production validation in progress.

## Scope

This pass prioritizes the PC admin and Portal paths required for an early
commercial launch. Mobile layout polish and an operator identity are deferred.
The only product identities in scope are `platform_admin` and Portal `user`.

Cloud remains the hosted runtime and service-detail layer. WordPress approval,
router truth, and final writes remain local.

## Verified

- Admin package catalog exposes Free, Plus, Pro, and Agency in that order.
- Admin credit packs use CNY pricing and a 365-day validity period.
- Portal billing exposes Plus between Free and Pro and shows purchasable credit
  packs with one-year validity.
- Account, provider, service-settings, SMTP preview, and Alipay configuration
  surfaces load on a 1280px PC viewport without page-level horizontal overflow.
- Portal and admin browser sessions cannot substitute for each other.
- Local database migration state is `20260710_0057 (head)`; the obsolete
  `site_user_grants` table is absent.
- Public preflight against `https://cloud.npc.ink` passes health, login-page,
  anonymous admin protection, and Alipay callback safety checks.

## Open Production Gates

- Run the formal production smoke with the production internal/admin tokens,
  real Portal mailbox, and real signed site credentials.
- Send a production login code to a real invited mailbox and confirm repeated
  delivery, not only the first message.
- Confirm `NPCINK_CLOUD_SERVICE_SETTINGS_SECRET` is stable on the release host
  and that SMTP/payment credentials remain readable after an API restart.
- Create a database backup and record the restore command before promotion.
- Review the existing `alembic check` index-name differences. The local database
  is at migration head, but autogenerate still reports historical index and
  unique-constraint naming differences that are outside the CNY migration.

## Release-Candidate Follow-up

- Portal authorization now uses `account_user_memberships` as its only truth.
- Alembic `20260710_0057` fails closed if legacy site-grant rows exist, then
  removes the obsolete table and adds the account-membership access index.
- The retired QQ callback, runtime config aliases, old cookies, and service-secret
  fallback are removed.
- Local API and workers restarted successfully with all three stored service
  credentials readable from the dedicated key only.
- PC Addon binding preserves its full query through email-code login and returns
  the complete payload to WordPress in Playwright coverage.

## Rollback

1. Record the current production release SHA and database backup before merge.
2. If the frontend/admin changes regress, redeploy the previous production SHA;
   do not rotate or remove `NPCINK_CLOUD_SERVICE_SETTINGS_SECRET`.
3. For an application-only rollback, preserve the database backup and the
   dedicated service-settings key. Downgrade `0057` only if the previous build
   still requires the empty compatibility table; do not expect old grant rows
   to be reconstructed.
4. Restore the database backup only for a confirmed data/schema incident, then
   rerun health, Portal login, provider runtime, payment callback, and SMTP smoke.

Production promotion remains blocked until the open production gates are
recorded as passed.
