# Live Site Addon Write Action Checklist: npcink.local

Date: 2026-06-20

## Purpose

This checklist turns the first real WordPress proof into a bounded, reversible
operation.

Target outcome:

- install and activate the Cloud addon on `npcink.local`;
- configure Cloud Base URL and a dedicated Cloud API Key through the addon
  `Save and Verify` path;
- prove the addon reaches `configured_valid`;
- stop before runtime smoke or Site Knowledge sync unless a separate approval
  names that next action.

This is a checklist only. It does not execute the write actions by itself.

## Boundary

Allowed after explicit approval for this checklist:

- WordPress plugin install and activation for `npcink.local`;
- Cloud service-plane provisioning of one dedicated live candidate site
  identity and API key;
- admin UI save-and-verify of Cloud Base URL and Cloud API Key;
- read-only post-change preflight.

Still no-go without a separate later approval:

- runtime smoke;
- Site Knowledge sync or search;
- content writes;
- proposal apply;
- direct database import;
- search-replace;
- enabling metadata monitoring;
- any operation on `wp.local` or `dbd.local`.

Cloud remains runtime/detail only. WordPress remains the local control plane and
write owner.

## Current Evidence

Target:

- hostname: `npcink.local`
- URL: `http://npcink.local/`
- WordPress root: `/Users/muze/Local Sites/npcink/app/public`
- Local run id: `PvPC4seEm`

Read-only preflight evidence:

- HTTP entrypoint returned `200`;
- WordPress `siteurl/home` is `http://npcink.local`;
- blog name is `npcink`;
- public posts/pages count is `1968`;
- current blocker is `cloud_addon_unverified`;
- current warning is `cloud_addon_plugin_not_active`.

Pre-write package:

- command:

```bash
scripts/live-site-addon-package.py \
  --output-dir .tmp/live-site-addon-package/npcink-20260620-prewrite
```

- generated local-only files:
  - `.tmp/live-site-addon-package/npcink-20260620-prewrite/snapshot.json`
  - `.tmp/live-site-addon-package/npcink-20260620-prewrite/summary.md`
  - `.tmp/live-site-addon-package/npcink-20260620-prewrite/npcink-pre-addon.sql`
- the database export is local-only and must not be committed.

Addon package:

- source repo: `/Users/muze/gitee/magick-ai-cloud-addon`
- build zip:
  `/Users/muze/gitee/magick-ai-cloud-addon/build/magick-ai-cloud-addon.zip`
- plugin basename after install:
  `magick-ai-cloud-addon/magick-ai-cloud-addon.php`
- display name: `Npcink Cloud Addon`
- settings option: `npcink_cloud_addon_settings`

## Required Approval Text

Before executing this checklist, get an explicit approval naming the exact
site and scope. Use this text:

```text
我明确批准在 npcink.local 安装并激活 Cloud addon，provision 专用 Cloud identity，
通过 addon 后台保存 Cloud Base URL 和 Cloud API Key 并验证；本次不运行 runtime
smoke，不运行 Site Knowledge sync/search，不写内容，不启用 monitoring。
```

If the approval omits the site, the addon install/activation, Cloud identity
provisioning, or the no-go exclusions, stop and ask again.

## Execution Sequence

The guarded helper for the install/activation portion is:

```bash
scripts/live-site-addon-install.py \
  --output-dir .tmp/live-site-addon-package/npcink-guarded-install
```

Default mode is prepare-only. It re-runs the pre-write package and writes an
install plan under `.tmp/`; it does not install or activate the plugin.

After the exact approval text above is provided, the install/activation step can
be executed with:

```bash
scripts/live-site-addon-install.py \
  --execute \
  --approval-text '<paste the exact approval text>' \
  --output-dir .tmp/live-site-addon-package/npcink-guarded-install
```

The helper only covers addon install/activation and read-only plugin-list
verification. It does not provision Cloud identity, does not write addon
settings, does not run runtime smoke, and does not run Site Knowledge
sync/search.

### 1. Re-run read-only preflight

```bash
scripts/live-site-preflight.py \
  --site npcink http://npcink.local/ "/Users/muze/Local Sites/npcink/app/public" \
  --markdown-out .tmp/live-site-preflight/npcink-before-addon-write.md \
  --json-out .tmp/live-site-preflight/npcink-before-addon-write.json
```

Expected result before install:

- same `siteurl/home`;
- addon not active;
- addon settings empty or unverified;
- no blocker other than Cloud addon readiness.

### 2. Re-run the pre-write package

```bash
scripts/live-site-addon-package.py \
  --output-dir .tmp/live-site-addon-package/npcink-before-addon-write
```

Continue only if the package reports:

- database export ok;
- addon zip exists;
- addon zip contains `magick-ai-cloud-addon/magick-ai-cloud-addon.php`;
- active plugin snapshot captured;
- `npcink_cloud_addon_settings` snapshot captured with secret presence only.

### 3. Prepare the WP-CLI target

Use the fresh package snapshot to avoid hard-coding a stale Local MySQL socket:

```bash
export NPCINK_WP_PATH="/Users/muze/Local Sites/npcink/app/public"
export NPCINK_WP_URL="http://npcink.local/"
export NPCINK_PACKAGE_DIR=".tmp/live-site-addon-package/npcink-before-addon-write"
export NPCINK_ADDON_ZIP="/Users/muze/gitee/magick-ai-cloud-addon/build/magick-ai-cloud-addon.zip"
export NPCINK_MYSQL_SOCKET="$(
  uv run python -c 'import json, os; print(json.load(open(os.environ["NPCINK_PACKAGE_DIR"] + "/snapshot.json"))["preflight"]["local_site"]["mysql_socket"])'
)"
```

Use this command shape for all WP-CLI calls:

```bash
/opt/homebrew/bin/php \
  -d "mysqli.default_socket=${NPCINK_MYSQL_SOCKET}" \
  -d "pdo_mysql.default_socket=${NPCINK_MYSQL_SOCKET}" \
  /opt/homebrew/bin/wp \
  --path="${NPCINK_WP_PATH}" \
  --url="${NPCINK_WP_URL}" \
  <wp-command>
```

### 4. Install and activate the addon

```bash
/opt/homebrew/bin/php \
  -d "mysqli.default_socket=${NPCINK_MYSQL_SOCKET}" \
  -d "pdo_mysql.default_socket=${NPCINK_MYSQL_SOCKET}" \
  /opt/homebrew/bin/wp \
  --path="${NPCINK_WP_PATH}" \
  --url="${NPCINK_WP_URL}" \
  plugin install "${NPCINK_ADDON_ZIP}" --force --activate
```

Verify activation:

```bash
/opt/homebrew/bin/php \
  -d "mysqli.default_socket=${NPCINK_MYSQL_SOCKET}" \
  -d "pdo_mysql.default_socket=${NPCINK_MYSQL_SOCKET}" \
  /opt/homebrew/bin/wp \
  --path="${NPCINK_WP_PATH}" \
  --url="${NPCINK_WP_URL}" \
  plugin list --fields=name,status,version --format=json
```

Expected addon row:

- `name`: `magick-ai-cloud-addon`
- `status`: `active`
- `version`: `0.1.0`

### 5. Provision a dedicated Cloud identity

Provision through Cloud service-plane/internal operations only.

Requirements:

- do not reuse `site_npcink_trial`;
- create a dedicated live candidate `site_id`;
- create one active API key for this site;
- issue the customer-facing Cloud API Key as `mak1_...` or JSON wrapper;
- do not write the secret to docs, commits, terminal transcripts intended for
  sharing, or WordPress debug output.

The public runtime API must not implicitly create or rotate the site/key.

### 6. Save and verify through wp-admin

Use the addon admin page rather than direct `wp option update`.

Reason:

- the admin action parses the customer-facing Cloud API Key;
- it stores internal `site_id / key_id / secret` server-side;
- it calls signed connectivity verification;
- it marks `verified` only after the probe passes.

Steps:

1. Log in to `http://npcink.local/wp-admin/` as a local administrator.
2. Open `Npcink > Cloud Addon`.
3. Enter the approved Cloud Base URL.
4. Paste the dedicated Cloud API Key.
5. Leave monitoring disabled.
6. Click `Save and Verify`.
7. Confirm the UI reports saved and verified state.
8. View source and confirm the Cloud secret is not printed.

Do not use direct option writes as the primary path. Direct option writes are
only acceptable for rollback with explicit approval because they bypass
save-and-verify.

### 7. Post-change read-only verification

Run:

```bash
scripts/live-site-preflight.py \
  --site npcink http://npcink.local/ "/Users/muze/Local Sites/npcink/app/public" \
  --markdown-out .tmp/live-site-preflight/npcink-after-addon-verify.md \
  --json-out .tmp/live-site-preflight/npcink-after-addon-verify.json
```

Expected result:

- HTTP remains `200`;
- `siteurl/home` remains `http://npcink.local`;
- addon is active;
- `base_url` is present;
- `site_id` is present;
- key/secret presence booleans are true;
- `verified` is true;
- no runtime smoke has been run;
- no Site Knowledge sync/search has been run;
- monitoring remains disabled.

## Stop Gate

Stop after configured verification succeeds.

The next phase needs a separate approval because runtime smoke and Site
Knowledge sync/search create Cloud runtime records and may read real site
content.

The next approval should name one of:

- runtime smoke only;
- Site Knowledge content sampling only;
- Site Knowledge sync/search proof;
- proposal/review/apply proof.

## Rollback

Rollback also requires explicit approval because it writes the WordPress site
state.

Preferred rollback path:

```bash
/opt/homebrew/bin/php \
  -d "mysqli.default_socket=${NPCINK_MYSQL_SOCKET}" \
  -d "pdo_mysql.default_socket=${NPCINK_MYSQL_SOCKET}" \
  /opt/homebrew/bin/wp \
  --path="${NPCINK_WP_PATH}" \
  --url="${NPCINK_WP_URL}" \
  plugin deactivate magick-ai-cloud-addon
```

If the pre-write snapshot showed empty addon settings, delete the addon option:

```bash
/opt/homebrew/bin/php \
  -d "mysqli.default_socket=${NPCINK_MYSQL_SOCKET}" \
  -d "pdo_mysql.default_socket=${NPCINK_MYSQL_SOCKET}" \
  /opt/homebrew/bin/wp \
  --path="${NPCINK_WP_PATH}" \
  --url="${NPCINK_WP_URL}" \
  option delete npcink_cloud_addon_settings
```

Then revoke the dedicated Cloud API key through Cloud service-plane/internal
operations.

Database import from
`.tmp/live-site-addon-package/npcink-before-addon-write/npcink-pre-addon.sql`
is the last-resort rollback and must not be used unless the site state is
actually damaged and the user explicitly approves DB import.

## Evidence to Keep

Keep under `.tmp/` only:

- before/after preflight Markdown and JSON;
- before/after package summaries;
- database export;
- redacted plugin and addon settings snapshots.

Commit only non-secret docs and scripts. Do not commit `.tmp/` outputs.
