# Production Backup Restore Drill - 2026-07-11

Status: passed.

## Objective

Verify that the production database after subscription-commerce migration
`20260710_0058` can be backed up, checksum-verified, restored into an isolated
database, queried, exported again, and removed without interrupting production.

## Production State

- Compute: 2 vCPU, 3.56 GiB RAM, no Swap.
- Public health before and after the drill: HTTP 200.
- Production migration: `20260710_0058`.
- Running production containers after the drill: 11.
- The real Alipay payment, Plus-to-Pro upgrade, refund, and QQ login checks are
  deferred until those provider credentials are configured.

## Backup Artifact

- Path:
  `/opt/npcink-ai-cloud/backups/post-0058-restore-drill-20260711T014702Z.dump`
- Format: PostgreSQL custom archive.
- Size: `3,203,166` bytes.
- Mode: `0600`.
- SHA-256:
  `28fecb2fa2524afd4fe8863bd25ef873acc2dbf56c97aef792292eb647fe9223`
- Archive-list and checksum verification: passed.

## Isolated Restore

- Temporary database: `npcink_restore_drill_20260711T014702Z`.
- Source migration: `20260710_0058`.
- Restored migration: `20260710_0058`.
- Public tables: 57.
- Commerce tables checked: `plan_offers`, `subscription_orders`,
  `trial_claims`.
- Plans: `free`, `plus`, `pro`, and `agency`, all active.
- Accounts: 3.
- Sites: 3.
- Account memberships: 1.
- Account subscriptions: 3.
- Plan offers: 2.
- Subscription orders: 1.
- Payment orders: 3, all pending test orders.
- Trial claims: 0.
- Service settings: 4.
- Legacy `site_user_grants`: absent.
- Schema-only export: passed.
- Data-only export: passed.
- Temporary database removal: confirmed.

The pending payment rows did not charge a customer. They were created while
preparing the deferred Alipay drill and remain subject to the existing 24-hour
unpaid-order expiry reconciliation.

## Safety Controls

- The restore used a strictly prefixed temporary database in the existing
  PostgreSQL cluster; no second PostgreSQL server was started.
- The script rejected the production database name and installed an exit trap
  that removed the temporary database on success or failure.
- No application process was pointed at the temporary database.
- Production remained healthy after backup, restore, export, and cleanup.
