# Real Site Trial Setup - npcink-trial - 2026-06-20

Status: controlled setup complete; runtime smoke and Site Knowledge sync not
started.

Purpose: move the selected `npcink-trial` clone from read-only preflight to a
dedicated Cloud identity and verified addon connection, without changing
WordPress content or starting Cloud execution against site content.

## Scope And Boundary

- WordPress target: `/Users/muze/Local Sites/npcink-trial/app/public`
- Stored WordPress URL: `http://127.0.0.1:8099`
- Cloud base URL: `http://127.0.0.1:8010`
- Cloud role: hosted runtime, entitlement/detail, verification, and evidence
- WordPress role: local control plane and final write owner
- Direct WordPress publishing: not used
- WordPress post/page mutation: not used
- Runtime execute: not run
- Site Knowledge sync/search/status: not run
- Batch article generation: not used
- Cloud prompt/router/workflow editor: not used
- Cloud skill registry or MCP platform: not used

This setup remains a local clone/staging rehearsal. It is not a live customer
trial and does not authorize any write to `npcink.local`, `dbd.local`,
`wp.local`, or another live site.

Historical ID note: this document records the old Free package IDs
`plan_free` / `plan_free_v1`; current package records use `free` / `free_v1`.

## Rollback Preparation

Before changing the addon option, a local addon option snapshot was saved:

```text
/Users/muze/gitee/npcink-cloud/.tmp/npcink-trial-setup-20260620/npcink_cloud_addon_settings-before-20260619165455.json
```

A full Local WordPress database export was also saved:

```text
/Users/muze/gitee/npcink-cloud/.tmp/npcink-trial-setup-20260620/npcink-trial-db-before-20260619165535.sql
```

Both files were set to local-only mode `600`.

The first `wp db export` attempt failed because `mysqldump` was not on the
default shell `PATH`. The database export was then completed with Local's
bundled `mysqldump` binary and the Local MySQL socket from `wp-config.php`.

## Dedicated Cloud Identity

Dedicated Cloud records were created for `npcink-trial`:

- Site ID: `site_npcink_trial`
- Account ID: `acct_site_npcink_trial`
- Subscription ID: `sub_site_npcink_trial`
- Plan: `plan_free`
- Plan version: `plan_free_v1`
- Key ID: `key_npcink_trial_20260620`
- Key status: active
- Site status: active
- Subscription status: active
- Key scopes:
  - `catalog:read`
  - `runtime:resolve`
  - `runtime:execute`
  - `runtime:read`
  - `stats:read`
  - `entitlement:read`

Secrets and customer-facing Cloud API Key values were not written to this
document.

## Controlled WordPress Write

Exactly one intended WordPress-side write was performed:

- option: `npcink_cloud_addon_settings`
- target site: `npcink-trial`
- previous Cloud site: `site_npcink_local`
- new Cloud site: `site_npcink_trial`

No WordPress posts, pages, taxonomies, users, menus, media records, or unrelated
options were changed by this setup pass.

## Addon Verification

The addon settings now point to the dedicated Cloud site:

- `base_url`: `http://127.0.0.1:8010`
- `site_id`: `site_npcink_trial`
- `key_id`: `[REDACTED_SECRET]`
- `secret`: `[REDACTED_SECRET]`
- `verified`: `true`
- `verified_at`: `2026-06-19 16:56:58 UTC`
- `last_verification_error`: empty
- `monitoring_enabled`: `true`

The addon signed connectivity probe passed:

- `live_ok`: true
- `auth_ok`: true
- Live message: `service is live`
- Auth message: signed Cloud request verified

The Cloud `site_api_keys.last_used_at` value updated during this verification:

- `2026-06-19 16:56:58.992306+00:00`

## Cloud Read Verification

Cloud service-plane read checks confirmed:

- `site_npcink_trial` is active.
- `acct_site_npcink_trial` is bound to the site.
- `sub_site_npcink_trial` is active.
- `key_npcink_trial_20260620` is active.
- The key is not expired or revoked.
- Entitlement snapshot is active for `plan_free_v1`.

Counts after setup:

- `run_records`: 0
- `usage_meter_events`: 0
- `provider_call_records` for this site's runs: 0
- `site_knowledge_documents`: 0
- `site_knowledge_chunks`: 0

These zero counts are expected. This setup intentionally stopped before runtime
execute and before Site Knowledge ingestion.

## WordPress Content Verification

Published content counts remained consistent with preflight:

- public `post` / `page`: `1968`
- public `post`: `1967`
- public `page`: `1`

## Go / No-Go

Current decision: setup complete; hold before runtime execution.

Blockers cleared:

- rollback artifacts exist;
- `npcink-trial` no longer shares Cloud evidence with `site_npcink_local`;
- addon credentials verify with a dedicated Cloud site and key.

Still not started:

- runtime smoke;
- usage / credit / billing evidence for an actual hosted runtime call;
- Site Knowledge sync;
- Site Knowledge search;
- Site Knowledge status polling.

## Next Safe Action

After explicit approval, run the next bounded phase:

1. one minimal read-only hosted runtime smoke through the verified addon;
2. record run, usage, credit ledger, entitlement, and billing/detail evidence;
3. stop and record the result before any Site Knowledge sync.

Do not enable:

- direct publishing;
- article body generation;
- batch article generation;
- Cloud prompt/router/workflow editing;
- Cloud skill registry;
- MCP platform behavior;
- live-site writes.
