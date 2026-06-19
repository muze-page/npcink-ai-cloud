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

Checked site roots:

- `/Users/muze/Local Sites/wp/app/public`
- `/Users/muze/Local Sites/npcink/app/public`
- `/Users/muze/Local Sites/dbd/app/public`

Checked HTTP entrypoints:

- `http://wp.local/`
- `http://npcink.local/`
- `http://dbd.local/`

## Findings

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

The three provided HTTP entrypoints are reachable, but the active WordPress
state exposed through WP-CLI is not a content-rich live candidate. All three
site roots currently resolve to the same small/default WordPress identity:
`magick-device-manage.local`.

This is unsuitable for the next live proof stage because:

- the active content set is too small to prove real Site Knowledge behavior;
- internal WordPress identity does not match the candidate domains;
- Cloud addon settings are empty and unverified;
- the expected Cloud addon is not configured for a dedicated site identity;
- running sync/runtime now would prove little and could blur environment
  ownership.

The most likely issue is Local site/domain/database mapping, or an intended
database dump that has not been loaded into the active Local instance.

## Automated Recheck

The repeatable preflight tool was run after this package was created. It
confirmed the same no-go decision for all three candidates:

- `wp`: `wordpress_identity_mismatch`, `content_set_too_small`,
  `cloud_addon_unverified`
- `npcink`: `wordpress_identity_mismatch`, `content_set_too_small`,
  `cloud_addon_unverified`
- `dbd`: `wordpress_identity_mismatch`, `content_set_too_small`,
  `cloud_addon_unverified`

The generated evidence remains local under `.tmp/live-site-preflight/` and is
not treated as a committed source of truth. Re-run the tool after a candidate's
Local mapping or active database is corrected.

## Go / No-Go

GO:

- Keep this as a read-only preflight record.
- Use it to decide the next candidate preparation step.
- Re-run read-only preflight after one candidate site is corrected or cloned.

NO-GO:

- Do not run live runtime smoke on `wp.local`, `npcink.local`, or `dbd.local`
  in their current state.
- Do not run live Site Knowledge sync/search on these sites in their current
  state.
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

Choose one candidate site and fix or confirm its active Local mapping so that
browser, WP-CLI, `siteurl/home`, and the active database all point to the same
intended WordPress instance.

After that, rerun this same read-only preflight. If the candidate then exposes a
real content set and a clear Cloud addon path, proceed to a separate live-site
setup package with backup, dedicated Cloud identity, and a narrow runtime smoke
plan.
