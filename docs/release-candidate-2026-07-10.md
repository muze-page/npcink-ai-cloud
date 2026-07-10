# PC Launch Release Candidate - 2026-07-10

Status: deployed to production and validated as a PC launch candidate; not yet
declared generally available.

## Scope

- PC Admin and Portal launch paths
- `platform_admin` and Portal `user` identity model only
- account membership as the only Portal authorization truth
- WordPress Addon login and binding continuity
- canonical configuration, QQ callback, cookies, and service-setting encryption

Cloud remains the hosted runtime and service-detail layer. This candidate does
not add WordPress writes, approval truth, Ability/Workflow registries, or a
second WordPress control plane.

## Landed Changes

- PR `#146` landed the PC Admin/Portal commercial polish and SMTP failure
  redaction.
- PR `#147` landed the Portal account-authorization hard cutover.
- Alembic `20260710_0057` removed `site_user_grants`, added the indexed
  account-membership lookup path, and fails closed if legacy grants exist.
- Retired runtime aliases, the old QQ callback, old cookies, the service-secret
  fallback, and the remaining targeted Mypy exceptions were removed.
- PR `#148` promoted the hard cutover to production with operator approval.
- PRs `#149` and `#150` aligned the standalone frontend dependency lock with
  the secure PostCSS and esbuild versions and promoted the fix to production.

## Verification Evidence

- focused Portal/Admin/API/contract tests: passed
- frontend contracts, TypeScript, ESLint, and production build: passed
- PC Playwright login and Addon binding: passed
- Mypy and Ruff: passed
- PostgreSQL migration `upgrade -> downgrade -> upgrade`: passed locally
- production migration: `20260710_0057 (head)`
- obsolete `site_user_grants` table: absent in production and restored backup
- production SMTP: three consecutive real-mailbox deliveries passed
- service-setting encryption: three settings readable with the dedicated key;
  retired key fallbacks rejected the ciphertexts
- production signed runtime: catalog, execute, run/result, stats, usage, health,
  and perimeter passed
- production workers: runtime, callback, and ops heartbeats fresh
- production cadence: all required tasks fresh during release validation
- dependency audit: no open Dependabot security alerts
- production release run `29084936244`: success in `9m41s`; deploy `4m07s`;
  post-production smoke `15s`
- production backup restore drill: passed; see
  [Production Backup Restore Drill - 2026-07-10](production-backup-restore-drill-2026-07-10.md)

## Production Promotion

- Initial hard-cutover production commit:
  `6f1b7b9829971d22e15d58b2c41a20db29db0351`
- Current production commit:
  `c5fdfe7a91b74c4bbc81564e9d5088102b53abde`
- Current production release directory:
  `/opt/npcink-ai-cloud/release-20260710100807`
- Current production and `master` file content: identical

## Remaining Gates Before General Availability

- complete formal `deploy/release-smoke.sh` with the required Portal, Admin,
  internal, and signed-runtime smoke credentials; the production workflow ran
  public preflight but skipped this optional step because those secrets were
  absent
- one real low-value Alipay transaction, including callback and credit grant
- one real WordPress Addon reconnect on production
- review of historical Alembic index-name drift
- production trace query confirmation
- 24-hour production observation window
- QQ login configuration and real callback smoke only if QQ login is enabled

## Rollback

Redeploy the previous production release for application regressions and retain
the dedicated service-settings key. For a confirmed database incident, use the
verified restore artifact documented in the backup drill, restore into a new
database first, validate migration and critical rows, then perform a controlled
traffic switch. Never overwrite the live production database while writers are
running.
