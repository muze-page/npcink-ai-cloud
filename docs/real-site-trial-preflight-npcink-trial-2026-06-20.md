# Real Site Trial Preflight - npcink-trial - 2026-06-20

Status: read-only preflight complete; execution blocked until backup and
dedicated Cloud identity are prepared.

Purpose: select and inspect one real-content staging or clone target for the
next Cloud-hosted runtime and Site Knowledge rehearsal. This pass did not
change WordPress content, WordPress options, Cloud keys, Cloud site records, or
Cloud runtime data.

## Target Decision

Use `npcink-trial` as the next candidate, not the direct `.local` sites and not
the lower-volume `dbd-trial` clone.

Reasons:

- it is a clone-style Local WordPress environment, not the direct live-looking
  `.local` site;
- it has an independent database;
- it has the required NPCInk/Magick plugin stack active;
- it has substantially more public content than `dbd-trial`, which makes Site
  Knowledge sync/search behavior more realistic;
- it can still be stopped before any live-site write.

`dbd-trial` remains a fallback candidate, but its smaller public corpus makes it
less useful for the next evidence pass.

## Boundary

- Cloud remains hosted runtime, usage, billing/detail, run detail, and evidence.
- Cloud must not become a second WordPress control plane.
- Cloud must not become a second ability registry, workflow registry, prompt
  editor, router editor, MCP platform, scheduler, or publishing surface.
- WordPress remains the final write owner.
- Site Knowledge output must remain `suggestion_only`.
- `direct_wordpress_write` must remain false.
- No article body, article title, SEO copy, full draft, batch generation, or
  ready-to-publish output is in scope.

## Read-Only WordPress Findings

- Target slug: `npcink-trial`
- Target environment: clone / staging-style local environment
- WordPress path: `/Users/muze/Local Sites/npcink-trial/app/public`
- Stored site URL: `http://127.0.0.1:8099`
- Stored home URL: `http://127.0.0.1:8099`
- Database name: `local_npcink_trial_20260617`
- Table prefix: `wp_`
- Multisite: no
- WordPress version: `7.0`
- Active theme: `twentytwentyfive` `1.5`
- Public `post` / `page` count observed: `1968`
- Public `post` count observed: `1967`
- Public `page` count observed: `1`
- Draft/private/pending/future count observed: `291`

Active plugins:

- `npcink-governance-core` `0.1.0`
- `npcink-abilities-toolkit` `0.5.1`
- `npcink-cloud-addon` `0.1.0`
- `npcink-toolbox` `0.1.0`
- `wordpress-importer` `0.9.5`

Content posture from sampled titles: WordPress, plugin, theme, design, code,
and web-publishing material. No category-level blocker was visible from the
sampled public titles, but a fuller content category review is still required
before execution.

## Addon State

The Cloud addon is installed, active, and currently reports a verified state.

Current blocker: the existing addon settings point at the shared local Cloud
site identity `site_npcink_local`.

Do not reuse that identity for this trial. Reusing it would mix usage, credit
ledger, billing/detail, Site Knowledge, and run evidence across multiple
WordPress targets.

Credential handling:

- addon API key, secret, and split credential values were not recorded here;
- any future option snapshot must be stored outside Git or with secrets
  redacted;
- shared notes and commits must use `[REDACTED_SECRET]` for credential fields.

## Cloud Findings

Local Cloud service was reachable during preflight:

- `/health/live`: ok
- local Docker development stack: API, workers, Postgres, Redis, proxy, and
  frontend were running, with database/cache services healthy.

This only proves the local Cloud stack is available. It does not yet prove that
`npcink-trial` has a dedicated service-plane account, subscription, site, or
active key.

## Execution Blockers

Do not start the `npcink-trial` runtime or Site Knowledge execution until all
items below are complete:

1. Confirm a rollback path for the WordPress clone.
2. Save the current `npcink_cloud_addon_settings` option snapshot with secrets
   protected.
3. Provision a dedicated Cloud identity for this target, for example:
   - account: `acct_site_npcink_trial`
   - site: `site_npcink_trial`
   - subscription: `sub_site_npcink_trial`
   - key: a dedicated active site API key
4. Update only the Cloud addon settings option after snapshot and approval.
5. Verify the addon points to the dedicated Cloud site.
6. Reconfirm Site Knowledge request limits and `suggestion_only` result shape.
7. Get a second explicit approval before any write to an actual live site.

## Go / No-Go

Current decision: go for provisioning planning; no-go for execution.

Allowed next step:

- prepare the dedicated Cloud service-plane identity and a rollback-aware addon
  update plan for `npcink-trial`.

Still not allowed:

- changing content on `npcink.local`, `dbd.local`, `wp.local`, or any live site;
- changing content on `npcink-trial`;
- changing any WordPress option except the Cloud addon setting, and only after
  snapshot and explicit approval;
- starting a Site Knowledge sync under the shared `site_npcink_local`
  identity.

## Next Safe Action

After approval, perform one bounded setup phase:

1. create or confirm a rollback point for `npcink-trial`;
2. snapshot the existing Cloud addon option without exposing secrets;
3. provision the dedicated Cloud account/site/subscription/key;
4. write only the Cloud addon setting to the dedicated identity;
5. verify addon status;
6. stop and record the setup result before runtime smoke or Site Knowledge sync.
