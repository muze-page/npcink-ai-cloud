# Live Site Preflight Package: wp.local / npcink.local / dbd.local

Date: 2026-06-20

## Purpose

Assess whether the user-provided local WordPress sites are ready to become the
first live-site proof target after the `npcink-trial` staging validation.

The target outcome is not to expand Cloud product scope. The target is to prove
that Magick AI Cloud can safely operate beside a real WordPress site as a hosted
runtime/detail layer while WordPress remains the control plane and write owner.

## Boundary

This preflight was read-only.

No live Cloud runtime execution was started. No Site Knowledge sync or search
was run against these sites. No Cloud identity was provisioned for them. No
WordPress options, content, plugins, database rows, files, or addon settings
were changed.

Live runtime smoke, live Site Knowledge sync/search, Cloud identity
provisioning, addon option writes, database import/search-replace, and content
writes remain no-go until a specific site is confirmed, backup/rollback exists,
and the user gives a second explicit approval for the exact action.

## Method

`wp` could not be used directly in this environment because the executable path
depends on `/usr/bin/env php`. The working read-only invocation was:

```bash
/opt/homebrew/bin/php /opt/homebrew/bin/wp --path="<site-path>" --url="<site-url>" ...
```

HTTP checks used `curl` GET requests only. WordPress checks used read-only
WP-CLI commands and a read-only `wp eval` summary for options, plugin state,
content counts, and Cloud addon settings.

The repeatable preflight command is now:

```bash
scripts/live-site-preflight.py \
  --markdown-out .tmp/live-site-preflight/wp-npcink-dbd-2026-06-20.md \
  --json-out .tmp/live-site-preflight/wp-npcink-dbd-2026-06-20.json
```

The command exits `0` only when every candidate is ready. It exits `2` for a
valid read-only no-go result. It prints candidate progress to stderr and writes
non-secret Markdown/JSON evidence to `.tmp/`.

By default, the command reads Local's `sites.json` and applies the matching
Local MySQL socket to WP-CLI. This is required for Local sites whose
`wp-config.php` uses `DB_HOST=localhost`; otherwise WP-CLI can connect to the
wrong default socket even though the browser routes to the correct Local site.
Use `--no-local-socket` only when intentionally testing the generic WP-CLI path.

Checked site roots:

- `/Users/muze/Local Sites/wp/app/public`
- `/Users/muze/Local Sites/npcink/app/public`
- `/Users/muze/Local Sites/dbd/app/public`

Checked HTTP entrypoints:

- `http://wp.local/`
- `http://npcink.local/`
- `http://dbd.local/`

## Initial Findings

| Candidate | HTTP status | Page title | WordPress internal siteurl/home | Blog name | Public posts/pages | Attachments | Cloud addon settings | Current decision |
| --- | ---: | --- | --- | --- | ---: | ---: | --- | --- |
| `wp.local` | 200 | `wp` | `http://magick-device-manage.local` | `magick-device-manage` | 2 | 0 | Empty, unverified | No-go |
| `npcink.local` | 200 | `npcink` | `http://magick-device-manage.local` | `magick-device-manage` | 2 | 0 | Empty, unverified | No-go |
| `dbd.local` | 200 | `dbd` | `http://magick-device-manage.local` | `magick-device-manage` | 2 | 0 | Empty, unverified | No-go |

Shared WordPress state observed through WP-CLI:

- `DB_NAME`: `local`
- table prefix: `wp_`
- multisite: `false`
- WordPress version: `7.0`
- active theme: `twentytwentyfive 1.5`
- active plugins:
  - `magick-device-manage/magick-device-manage.php`
  - `npcink-abilities-toolkit/npcink-abilities-toolkit.php`
  - `npcink-ai-client-adapter/npcink-ai-client-adapter.php`
  - `plugin-check/plugin.php`
- sample public titles:
  - `Hello world!`
  - `Sample Page`

Cloud addon option snapshot:

- `base_url`: empty
- `site_id`: empty
- `key_id`: not present
- `secret`: not present
- `api_key`: not present
- `timeout`: `0`
- `verified`: `false`
- `verified_at`: empty
- `monitoring`: `false`

Local SQL dump files exist for all three Local sites. Their size and simple
pattern counts suggest that `npcink` and `dbd` may have more content in dump
files than the currently active WordPress database exposes through WP-CLI. This
was not imported or modified.

## Interpretation

The first WP-CLI pass used the generic PHP/WP-CLI path and showed all three site
roots resolving to the same small/default WordPress identity:
`magick-device-manage.local`. That result was not the true browser-routed Local
site state; it was a WP-CLI targeting problem caused by `DB_HOST=localhost`
without the matching Local MySQL socket.

This is unsuitable for the next live proof stage because:

- the active content set is too small to prove real Site Knowledge behavior;
- internal WordPress identity does not match the candidate domains;
- Cloud addon settings are empty and unverified;
- the expected Cloud addon is not configured for a dedicated site identity;
- running sync/runtime now would prove little and could blur environment
  ownership.

The underlying Local site/domain/database mapping is valid. The repeatable
preflight tool now resolves the matching Local MySQL socket before reading
WordPress state.

## Automated Recheck

The repeatable preflight tool was updated to apply Local's per-site MySQL socket
and was run again. It confirmed that the three candidates now expose their
browser-routed WordPress identities through WP-CLI:

| Candidate | HTTP status | WordPress internal siteurl/home | Blog name | Public posts/pages | Remaining blocker |
| --- | ---: | --- | --- | ---: | --- |
| `wp.local` | 200 | `http://wp.local` | `wp` | 59 | `cloud_addon_unverified` |
| `npcink.local` | 200 | `http://npcink.local` | `npcink` | 1968 | `cloud_addon_unverified` |
| `dbd.local` | 200 | `http://dbd.local` | `dbd` | 134 | `cloud_addon_unverified` |

Current candidate priority:

- `npcink.local` is the best first live proof candidate because it has the
  largest content set and a clean site identity match.
- `dbd.local` and `wp.local` are viable secondary candidates after content
  category review.

The current no-go reason is no longer content or identity mismatch. The current
blocker is Cloud addon readiness:

- the Cloud addon is not installed in the three candidate plugin directories;
- the Cloud addon is not active;
- Cloud addon settings are empty and unverified;
- no dedicated live Cloud identity has been provisioned for any candidate.

The generated evidence remains local under `.tmp/live-site-preflight/` and is
not treated as a committed source of truth. Re-run the tool after a candidate's
Cloud addon installation/configuration state changes.

## Go / No-Go

GO:

- Keep this as a read-only preflight record.
- Use it to decide the next candidate preparation step.
- Use `npcink.local` as the preferred first live proof candidate.
- Prepare a separate addon installation and verification plan for one selected
  candidate.
- Re-run read-only preflight after addon install/configuration state changes.

NO-GO:

- Do not run live runtime smoke on `wp.local`, `npcink.local`, or `dbd.local`
  until the Cloud addon is installed, active, configured, and verified.
- Do not run live Site Knowledge sync/search on these sites until addon
  readiness and a dedicated Cloud identity are confirmed.
- Do not reuse `site_npcink_trial` for any live candidate.
- Do not provision a live Cloud identity until the exact candidate is selected.
- Do not write addon options, import databases, run search-replace, activate
  plugins, or change WordPress content without explicit approval and rollback.

## Requirements Before Live Candidate Execution

Before any live execution, the selected site needs:

1. Exact candidate selected by hostname and WordPress root.
2. Active database/content confirmed through WP-CLI and browser, not only by an
   SQL dump file.
3. Fresh database and files backup.
4. Cloud addon installed/active or an approved install/activation step.
5. Dedicated live Cloud site identity, account/subscription/plan, and API key.
6. Addon option snapshot before any configuration write.
7. Rollback plan for addon settings and Cloud key revocation.
8. Content/PII category sampling for Site Knowledge safety.
9. Second explicit user approval naming the exact live site and exact action.

## Next Safe Action

Choose one candidate site, preferably `npcink.local`, and prepare a narrow
Cloud addon installation/configuration package.

That package must include backup/rollback, the exact plugin source/package,
dedicated Cloud identity creation, addon option snapshot, and a second explicit
approval before any WordPress write or Cloud identity provisioning happens.
