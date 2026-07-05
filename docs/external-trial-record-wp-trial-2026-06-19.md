# External Trial Record - wp-trial - 2026-06-19

Status: local trial-clone rehearsal complete; not an external customer invite.

Purpose: verify one isolated local WordPress trial clone against a dedicated
Cloud site identity, so Cloud runtime, addon verification, usage, credit ledger,
entitlement, and billing/detail evidence do not mix with the previous
`npcink.local` rehearsal.

## Scope And Boundary

- WordPress target: `/Users/muze/Local Sites/wp-trial/app/public`
- Stored WordPress URL: `http://127.0.0.1:8098`
- Cloud base URL: `http://127.0.0.1:8010`
- WordPress administrator username: `1`
- WordPress administrator password: `[REDACTED_SECRET]`
- Cloud role: runtime/detail/evidence only
- Local WordPress/Core role: control plane and final write owner
- Direct WordPress publishing: not used
- Batch article generation: not used
- Cloud prompt/router/workflow editor: not used
- Cloud skill registry or MCP platform: not used

This record is local/staging rehearsal evidence. It must not be counted as a
real external customer trial.

Historical ID note: this document records the old Free package IDs
`plan_free` / `plan_free_v1`; current package records use `free` / `free_v1`.

## Preflight Findings

The initial direct candidates `wp.local`, `npcink.local`, and `dbd.local` were
not used for this rehearsal because their local directories all pointed at the
same database name, `local`, with the same `wp_` table prefix.

`wp-trial` was selected instead because:

- it has an independent database: `local_wp_trial_20260617`
- it has the required plugin stack active:
  - `npcink-governance-core`
  - `npcink-abilities-toolkit`
  - `npcink-cloud-addon`
  - `npcink-toolbox`
- it contains richer theme test content than the default direct `.local`
  candidates

## Controlled Write Performed

Only the `wp-trial` Cloud addon settings and Cloud service-plane records were
changed.

Before changing the addon option, a local option snapshot was saved at:

```text
/Users/muze/gitee/npcink-cloud/.tmp/wp-trial-rehearsal/npcink_cloud_addon_settings-before-20260619153319.json
```

The full DB export command could not run from the default shell initially
because `mysql` / `mysqldump` were not on `PATH`. The actual write was limited
to one addon option, and the option snapshot is enough to restore that setting.

## Dedicated Cloud Identity

Dedicated Cloud records were created for `wp-trial`:

- Site ID: `site_wp_trial`
- Account ID: `acct_site_wp_trial`
- Subscription ID: `sub_site_wp_trial`
- Plan: `plan_free`
- Plan version: `plan_free_v1`
- Key ID: `key_wp_trial_20260619`
- Key status: active
- Key scopes:
  - `catalog:read`
  - `runtime:resolve`
  - `runtime:execute`
  - `runtime:read`
  - `stats:read`
  - `entitlement:read`

Secrets were not written to this document.

## Addon Verification

The `npcink_cloud_addon_settings` option now points to the dedicated Cloud
site:

- `base_url`: `http://127.0.0.1:8010`
- `site_id`: `site_wp_trial`
- `key_id`: `[REDACTED_SECRET]`
- `secret`: `[REDACTED_SECRET]`
- `verified`: `true`
- `verified_at`: `2026-06-19 15:35:35 UTC`
- `monitoring_enabled`: `true`

The addon signed connectivity probe passed:

- `live_ok`: true
- `auth_ok`: true
- Live message: `service is live`
- Auth message: signed Cloud request verified

Addon entitlement summary synced:

- State: cached
- Available: true
- Package label: Free
- Entitlement status: active
- Contract version: `cloud-billing-entitlement-v1`
- `direct_wordpress_write`: false

## Runtime Evidence

A minimal read-only hosted runtime request was sent through the `wp-trial`
addon runtime client.

Result:

- Run ID: `run_d9a02fd4b5ac4744a7aff82caa4f1722`
- Status: succeeded
- Provider ID: `openai`
- Model ID: `ByteDance-Seed/Seed-OSS-36B-Instruct`
- Fallback used: false
- Output preview: `The WP Trial read-only hosted runtime path operates correctly.`

No WordPress content was written by this runtime request.

## Usage, Credit, And Billing Evidence

The dedicated `site_wp_trial` records showed the expected runtime usage.

Usage meter:

- Runs: 2
- Provider calls: 2
- Input tokens: 54
- Output tokens: 169
- Total tokens: 223

AI credit ledger:

- Account: `acct_site_wp_trial`
- Entries: 6
- Total recorded credits: 4
- Rate version: `ai-credit-ledger-v2`
- Breakdown:
  - Hosted runs: 2 credits
  - Model tokens: 2 credits
  - Other provider calls: 0 credits

Billing/detail snapshot:

- Snapshot ID:
  `bill_site_wp_trial_sub_site_wp_trial_1781883256_1784475256`
- Totals reconciled with usage:
  - Runs: 2
  - Provider calls: 2
  - Input tokens: 54
  - Output tokens: 169
  - Total tokens: 223

Entitlement usage totals matched the billing snapshot totals.

## Go / No-Go

Decision: go for local `wp-trial` rehearsal only.

External invite decision: hold. This is still local/staging evidence, not an
external customer trial.

Blockers cleared:

- `wp-trial` no longer shares Cloud evidence with `site_npcink_local`.
- Addon credentials verify with a dedicated Cloud site and key.
- Runtime, usage meter, AI credit ledger, entitlement, and billing/detail
  evidence all point to `site_wp_trial`.

Remaining limitations:

- The local web server for `http://127.0.0.1:8098` was not reachable from
  `curl` during preflight, although WP-CLI access worked.
- Site Knowledge over actual `wp-trial` content was not run in this pass.
- This does not replace a real external low-risk customer/site trial.

## Next Safe Action

If continuing, use this same dedicated `site_wp_trial` identity to run a
bounded Site Knowledge / reviewable-assistance rehearsal against `wp-trial`
content.

Do not enable:

- direct publishing
- batch article generation
- Cloud prompt/router/workflow editing
- Cloud skill registry
- MCP platform behavior
- customer self-serve payment or checkout
