# Live Site Addon Setup Plan: npcink.local

Date: 2026-06-20

## Purpose

Prepare the first live-site Cloud proof candidate after the Local socket-aware
preflight corrected WP-CLI targeting.

The target remains narrow: prove Magick AI Cloud can serve a real WordPress site
as a hosted runtime/detail layer while WordPress keeps configuration, approval,
and write ownership.

## Current Candidate

Preferred candidate: `npcink.local`

Read-only evidence:

- HTTP entrypoint: `200`
- WordPress `siteurl/home`: `http://npcink.local`
- Blog name: `npcink`
- Public posts/pages: `1968`
- Local mapping: matched through Local app metadata
- MySQL service: Local per-site socket, not the generic `localhost` default
- Current active plugin set: `wordpress-importer`
- Cloud addon: not installed, not active, not configured, not verified

## Addon Source

Candidate addon package:

- Source repo: `/Users/muze/gitee/magick-ai-cloud-addon`
- Build package: `/Users/muze/gitee/magick-ai-cloud-addon/build/magick-ai-cloud-addon.zip`
- Main plugin file in build: `magick-ai-cloud-addon/magick-ai-cloud-addon.php`
- Source repo status at inspection time: clean

Observed addon contract:

- Plugin name: `Npcink Cloud Addon`
- Version: `0.1.0`
- Settings option: `npcink_cloud_addon_settings`
- Settings fields are Cloud Base URL and Cloud API Key.
- The addon parses the Cloud API Key into server-side `site_id / key_id /
  secret` signing credentials.
- Split credentials must not be exposed as UI fields or debug output.

## Current Go / No-Go

GO:

- Continue read-only preparation.
- Treat `npcink.local` as the first live proof candidate.
- Prepare exact installation, backup, identity, and rollback steps.
- Re-run `scripts/live-site-preflight.py` after addon state changes.
- Generate the pre-write backup/snapshot package before requesting install
  approval.

NO-GO without second explicit approval:

- Do not install or activate the addon.
- Do not write WordPress options.
- Do not provision a Cloud live identity.
- Do not paste or persist a Cloud API Key.
- Do not run runtime smoke.
- Do not run Site Knowledge sync/search.
- Do not import, search-replace, or otherwise mutate the WordPress database.

## Required Execution Package

Before any write action, prepare and confirm:

1. Exact target:
   - hostname: `npcink.local`
   - WordPress root: `/Users/muze/Local Sites/npcink/app/public`
   - Local run id: `PvPC4seEm`
2. Fresh backup:
   - database export from the `npcink.local` Local MySQL socket
   - files/plugin state snapshot
3. Addon install method:
   - install from the build zip or copy the build directory
   - activate only `magick-ai-cloud-addon/magick-ai-cloud-addon.php`
4. Pre-write snapshot:
   - current active plugins
   - current `npcink_cloud_addon_settings`
5. Dedicated Cloud identity:
   - do not reuse `site_npcink_trial`
   - create a live candidate identity only after approval
6. Addon configuration:
   - Cloud Base URL
   - customer-facing Cloud API Key
   - verification result
7. Rollback:
   - deactivate/remove addon
   - restore previous option snapshot
   - revoke Cloud key if one was issued
8. Verification after install/config:
   - run `scripts/live-site-preflight.py`
   - confirm only expected blockers remain or decision becomes `go`
   - only then consider a separate runtime smoke package

## Pre-Write Package Command

The repeatable package command is:

```bash
scripts/live-site-addon-package.py \
  --output-dir .tmp/live-site-addon-package/npcink-20260620-prewrite
```

This command:

- resolves the matching Local MySQL socket for `npcink.local`;
- snapshots active plugins;
- snapshots `npcink_cloud_addon_settings` with secret fields redacted;
- validates the addon build zip exists and contains the main plugin file;
- exports a pre-addon database backup into `.tmp/`;
- writes `snapshot.json` and `summary.md` into the output directory.

The package command was run successfully. The database export completed and the
backup file is local-only under `.tmp/live-site-addon-package/`. The output is
not committed because it may contain site content.

## Next Safe Action

Create the exact write-action checklist for `npcink.local` addon installation
and Cloud identity provisioning, then ask for explicit approval naming that
exact site and action before executing it.
