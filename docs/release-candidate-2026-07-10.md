# PC Launch Release Candidate - 2026-07-10

Status: code-complete candidate, not production-approved.

## Scope

- PC Admin and Portal launch paths
- `platform_admin` and Portal `user` identity model only
- account membership as the only Portal authorization truth
- WordPress Addon login and binding continuity
- canonical configuration, QQ callback, cookies, and service-setting encryption

Cloud remains the hosted runtime and service-detail layer. This candidate does
not add WordPress writes, approval truth, Ability/Workflow registries, or a
second WordPress control plane.

## Candidate Changes

- PR `#146` remains the validated base and is waiting for repository protection.
- `fb236844` removes `site_user_grants`, adds Alembic `0057`, and moves Portal
  list/detail access to indexed account-membership joins.
- The follow-up config commit removes retired aliases, the old QQ callback,
  old cookies, service-secret fallback, and two targeted-Mypy exceptions.

## Verification Evidence

- focused Portal/Admin/API/contract tests: 172 passed, 1 skipped
- Portal authorization and Addon focused tests: 161 passed
- frontend unit contracts: passed
- frontend TypeScript: passed
- PC Playwright login and Addon binding: 2 passed
- Mypy: 203 source files passed
- targeted Mypy debt files: 2 passed
- PostgreSQL migration: `upgrade -> downgrade -> upgrade` passed
- local database: `20260710_0057`; obsolete site-grant table absent
- local restart: API, runtime worker, callback worker, and ops worker healthy
- local stored service credentials: 3 configured values, all readable with the
  dedicated service-settings key only

## Production Gates

- merge PR `#146` through repository protection, then retarget this stacked PR
  to `master`
- confirm production `site_user_grants` count is zero before migration
- confirm production `.env.deploy` uses canonical names and a stable dedicated
  service-settings key
- confirm QQ Open Platform callback is `/open/auth/qq/callback`
- take and verify a database backup and rollback command
- run real mailbox, QQ, Alipay, and signed WordPress runtime smoke tests
- promote through the documented `master -> production` PR with operator approval

## Rollback

Revert the application commit and downgrade Alembic to `20260709_0056`. The
downgrade recreates an empty compatibility table; it does not reconstruct old
site-grant rows. Preserve `NPCINK_CLOUD_SERVICE_SETTINGS_SECRET` during rollback.
