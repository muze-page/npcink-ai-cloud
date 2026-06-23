# External Trial Candidate Preflight - Local WordPress Sites - 2026-06-19

Status: read-only preflight complete; isolated rehearsal not started.

Purpose: inspect the local WordPress candidates provided for the next
Cloud-hosted runtime rehearsal without changing WordPress content, plugin
configuration, Cloud keys, or Cloud site records.

This preflight used only public HTTP checks and WP-CLI read operations. The
administrator password was provided for local access but was not written to
this file.

## Candidate URLs Provided

- `http://wp.local/`
- `http://npcink.local/`
- `http://dbd.local/`

All three responded with `200 OK` and exposed WordPress markers through public
HTML or REST responses.

## Boundary

- This remains local/staging rehearsal work, not a real external customer
  trial.
- Cloud must remain runtime/detail/evidence only.
- WordPress/Core must remain the control plane and final write owner.
- No direct publishing, batch article generation, prompt/router editor,
  workflow builder, Cloud skill registry, MCP platform, or second scheduler was
  used or enabled.

## Read-Only Findings

### `wp.local`, `npcink.local`, and `dbd.local`

The three direct `.local` site directories exist:

- `/Users/muze/Local Sites/wp/app/public`
- `/Users/muze/Local Sites/npcink/app/public`
- `/Users/muze/Local Sites/dbd/app/public`

However, WP-CLI showed that all three direct directories use the same database
name and table prefix:

- `DB_NAME`: `local`
- `table_prefix`: `wp_`

WP-CLI also reported the same stored `siteurl` / `home` value for all three:

- `http://magick-device-manage.local`

Observed content and plugin posture were also equivalent:

- WordPress version: `7.0`
- Active theme: `twentytwentyfive`
- Active Magick/NPCInk plugins: none
- Plugin list: only `wordpress-importer`, inactive
- Content: default `Hello world!`, `Sample Page`, and draft `Privacy Policy`
- Administrator username: `1`
- Administrator password: `[REDACTED_SECRET]`

Conclusion: these direct `.local` sites should not be treated as three clean
independent trial targets. They appear to be aliases or similarly configured
local installs over the same baseline database state.

### Trial Clone Directories

Separate trial clone directories are present:

- `/Users/muze/Local Sites/wp-trial/app/public`
- `/Users/muze/Local Sites/npcink-trial/app/public`
- `/Users/muze/Local Sites/dbd-trial/app/public`

Each has an independent database name:

- `wp-trial`: `local_wp_trial_20260617`
- `npcink-trial`: `local_npcink_trial_20260617`
- `dbd-trial`: `local_dbd_trial_20260617`

Each trial clone has the required local plugin stack active:

- `npcink-governance-core`
- `npcink-abilities-toolkit`
- `npcink-cloud-addon`
- `npcink-toolbox`
- `wordpress-importer`

## Recommended Candidate

Use `wp-trial` as the first local real-content rehearsal target.

Reasons:

- independent trial database
- Magick/NPCInk plugin stack is already active
- Cloud addon is already installed and active
- content is richer than the direct `.local` defaults, using theme test content
- lower risk than touching the shared direct `.local` candidates

Observed `wp-trial` details:

- WordPress path: `/Users/muze/Local Sites/wp-trial/app/public`
- Stored site URL: `http://127.0.0.1:8098`
- WordPress version: `7.0`
- Active theme: `twentytwentyfive`
- Permalink structure: `/%postname%/`
- Administrator username: `1`
- Administrator password: `[REDACTED_SECRET]`
- Cloud addon settings option: `npcink_cloud_addon_settings`
- Cloud addon `base_url`: `http://127.0.0.1:8010`
- Cloud addon verified state: `true`
- Cloud addon verified at: `2026-06-07 05:21:28 UTC`

## Current Blocker Before Rehearsal

`wp-trial` currently points its Cloud addon at this Cloud site ID:

- `site_npcink_local`

That site ID was already used by the previous `npcink.local` local alpha
rehearsal. Reusing it would mix evidence across two WordPress targets and make
usage, credit ledger, billing/detail, audit, and guard records harder to
explain.

Do not start the isolated `wp-trial` rehearsal until it has its own Cloud site
identity, for example:

- `site_wp_trial`
- account: `acct_site_wp_trial`
- subscription: `sub_site_wp_trial`
- a dedicated active site API key

## Next Safe Action

After explicit approval, perform a bounded setup step:

1. Provision a dedicated Cloud runtime site for `wp-trial`.
2. Issue a dedicated Cloud API key for that site.
3. Update only the `wp-trial` Cloud addon settings to the dedicated site/key.
4. Verify the addon.
5. Run only the read/review/runtime evidence path.
6. Record a separate go/no-go document for `wp-trial`.

Do not change `wp.local`, `npcink.local`, `dbd.local`, `npcink-trial`, or
`dbd-trial` during the first `wp-trial` rehearsal.
