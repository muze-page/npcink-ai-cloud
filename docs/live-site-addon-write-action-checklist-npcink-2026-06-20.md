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

At any point, summarize the guarded trial chain with:

```bash
scripts/live-site-trial-status.py \
  --stage1-report .tmp/live-site-stage1/npcink-stage1/stage1-report.json \
  --acceptance-report .tmp/live-site-stage1-acceptance/npcink-stage1/acceptance-report.json \
  --resolve-smoke-report .tmp/live-site-runtime-smoke/npcink-resolve/runtime-resolve-smoke-report.json \
  --execute-smoke-report .tmp/live-site-runtime-execute-smoke/npcink-execute/runtime-execute-smoke-report.json \
  --output-dir .tmp/live-site-trial-status/npcink
```

This status helper only reads local reports and writes a summary. It does not
install plugins, write options, provision identity, call Cloud runtime, run Site
Knowledge, enable monitoring, or write content. Use it to identify the next
blocked phase and the exact approval text needed for that phase.

The first-stage guarded helper combines the addon install/activation guard and
the Cloud identity guard into one audit trail:

Before requesting the exact execute approval, run the read-only Stage 1
readiness gate:

```bash
scripts/live-site-stage1-readiness.py \
  --base-url http://127.0.0.1:8010 \
  --output-dir .tmp/live-site-stage1-readiness/npcink-stage1
```

This readiness gate checks the target site, Local MySQL socket, addon zip,
identity request plan, Cloud `/health/live`, and internal-token guarded
`/health/ready`. It does not install plugins, write options, provision Cloud
identity, call runtime, run Site Knowledge, enable monitoring, or write
content.

The readiness, identity, and Stage 1 helpers resolve
`MAGICK_CLOUD_INTERNAL_AUTH_TOKEN` in this order:

1. explicit `--internal-token`;
2. current process environment;
3. `.env`, then `.env.local`.

Reports only record token presence, source, and length; they do not print the
token value. Use `--env-file <path>` to override the default env-file list.

For any execute approval, prefer putting the exact approval text in a local
`.txt` file under `.tmp/` and passing `--approval-file <path>`. The guarded
helpers reject ambiguous input if both `--approval-text` and `--approval-file`
are provided. The file contents must still match the required approval text.

If it reports `ok=false`, fix those prerequisites before asking for Stage 1
execute approval. If it reports `ok=true`, the next remaining gate is still the
exact approval text below; readiness is not authorization.

Stage 1 execute also enforces this readiness gate internally before plugin
installation. If the readiness report fails, the helper stops before addon
install/activation and before Cloud identity provisioning.

```bash
scripts/live-site-stage1.py \
  --output-dir .tmp/live-site-stage1/npcink-stage1
```

Default mode is prepare-only. It re-runs the addon pre-write package, writes the
addon install plan, writes the Cloud internal service request plan, and emits:

- `.tmp/live-site-stage1/npcink-stage1/stage1-report.json`
- `.tmp/live-site-stage1/npcink-stage1/summary.md`
- `.tmp/live-site-stage1/npcink-stage1/addon-install/`
- `.tmp/live-site-stage1/npcink-stage1/identity/`

It does not install or activate the plugin, call the Cloud service, write addon
settings, run runtime smoke, run Site Knowledge sync/search, write content, or
enable monitoring.

After the exact approval text above is provided and
`MAGICK_CLOUD_INTERNAL_AUTH_TOKEN` is available, stage 1 can be executed with:

```bash
scripts/live-site-stage1.py \
  --execute \
  --approval-file .tmp/live-site-stage1/npcink-stage1-approval.txt \
  --base-url http://127.0.0.1:8010 \
  --output-dir .tmp/live-site-stage1/npcink-stage1
```

Execute mode first installs/activates the addon through the existing WP-CLI
guard. It provisions the dedicated Cloud identity only if the addon verifies as
active. It still stops before wp-admin Save and Verify, runtime smoke, Site
Knowledge sync/search, content writes, and monitoring.

If key issue succeeds, the customer-facing Cloud API Key is written only to
`.tmp/live-site-stage1/npcink-stage1/identity/cloud-api-key.secret.json`; do not
commit or paste that value into shared docs or terminal summaries.

Before opening wp-admin, generate the read-only Save and Verify handoff:

```bash
scripts/live-site-save-verify-handoff.py \
  --stage-report .tmp/live-site-stage1/npcink-stage1/stage1-report.json \
  --output-dir .tmp/live-site-save-verify-handoff/npcink-stage1
```

This handoff confirms Stage 1 was executed successfully, confirms the local
secret file exists and contains the required fields, and prints the exact addon
admin URL:

```text
http://npcink.local/wp-admin/admin.php?page=npcink-cloud-addon
```

It reports only secret presence and length. It does not print the Cloud API Key,
write WordPress options, provision Cloud identity, call runtime, run Site
Knowledge sync/search, enable monitoring, or write content.

After the addon admin page reports Save and Verify success, run the read-only
Stage 1 acceptance check:

```bash
scripts/live-site-stage1-acceptance.py \
  --stage-report .tmp/live-site-stage1/npcink-stage1/stage1-report.json \
  --output-dir .tmp/live-site-stage1-acceptance/npcink-stage1
```

The acceptance helper reruns read-only preflight and checks:

- Stage 1 was executed successfully;
- the generated secret file exists without printing the secret;
- the addon is active and verified in WordPress;
- the addon `site_id` matches the Stage 1 Cloud identity;
- monitoring remains disabled;
- no runtime smoke, Site Knowledge sync/search, content writes, or option
  writes were run by the acceptance step.

Only if this report says `ready_for_runtime_smoke_approval=true` should a
separate runtime smoke approval be requested.

The first runtime smoke is limited to a signed `/v1/runtime/resolve` request:

```bash
scripts/live-site-runtime-smoke.py \
  --acceptance-report .tmp/live-site-stage1-acceptance/npcink-stage1/acceptance-report.json \
  --stage-report .tmp/live-site-stage1/npcink-stage1/stage1-report.json \
  --output-dir .tmp/live-site-runtime-smoke/npcink-resolve
```

Default mode is prepare-only. It writes the request plan and boundary report but
does not call Cloud runtime.

After the acceptance report is ready and a separate approval names this exact
smoke, execute with:

```bash
scripts/live-site-runtime-smoke.py \
  --execute \
  --approval-file .tmp/live-site-runtime-smoke/npcink-resolve-approval.txt \
  --acceptance-report .tmp/live-site-stage1-acceptance/npcink-stage1/acceptance-report.json \
  --stage-report .tmp/live-site-stage1/npcink-stage1/stage1-report.json \
  --base-url http://127.0.0.1:8010 \
  --output-dir .tmp/live-site-runtime-smoke/npcink-resolve
```

Required approval text for this limited smoke:

```text
我明确批准在 npcink.local 运行一次 Cloud runtime resolve smoke；本次不运行 runtime
execute，不运行 Site Knowledge sync/search，不写 WordPress 内容，不启用 monitoring。
```

This smoke verifies signed runtime auth, the provisioned site/key, the execution
contract gate, and routing/profile resolution. It does not call
`/v1/runtime/execute`, run provider execution, run Site Knowledge, write
WordPress content, or enable monitoring.

Only after the resolve smoke report is `ok=true`, request separate approval for
one bounded `/v1/runtime/execute` smoke:

```bash
scripts/live-site-runtime-execute-smoke.py \
  --acceptance-report .tmp/live-site-stage1-acceptance/npcink-stage1/acceptance-report.json \
  --stage-report .tmp/live-site-stage1/npcink-stage1/stage1-report.json \
  --resolve-smoke-report .tmp/live-site-runtime-smoke/npcink-resolve/runtime-resolve-smoke-report.json \
  --output-dir .tmp/live-site-runtime-execute-smoke/npcink-execute
```

Default mode is prepare-only. It checks the acceptance and resolve-smoke reports
and writes the execute request plan without calling Cloud runtime.

Required approval text for this bounded execute smoke:

```text
我明确批准在 npcink.local 运行一次 Cloud runtime execute smoke；本次不运行 Site
Knowledge sync/search，不写 WordPress 内容，不启用 monitoring。
```

After that exact text is saved locally, execute with:

```bash
scripts/live-site-runtime-execute-smoke.py \
  --execute \
  --approval-file .tmp/live-site-runtime-execute-smoke/npcink-execute-approval.txt \
  --acceptance-report .tmp/live-site-stage1-acceptance/npcink-stage1/acceptance-report.json \
  --stage-report .tmp/live-site-stage1/npcink-stage1/stage1-report.json \
  --resolve-smoke-report .tmp/live-site-runtime-smoke/npcink-resolve/runtime-resolve-smoke-report.json \
  --base-url http://127.0.0.1:8010 \
  --output-dir .tmp/live-site-runtime-execute-smoke/npcink-execute
```

Execute mode sends one signed `/v1/runtime/execute` request using the same
dedicated site/key. It may trigger provider execution and record Cloud runtime
run evidence. It still does not run Site Knowledge sync/search, write WordPress
content, or enable monitoring.

The lower-level helpers remain available for focused debugging.

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
  --approval-file .tmp/live-site-addon-package/npcink-install-approval.txt \
  --output-dir .tmp/live-site-addon-package/npcink-guarded-install
```

The helper only covers addon install/activation and read-only plugin-list
verification. It does not provision Cloud identity, does not write addon
settings, does not run runtime smoke, and does not run Site Knowledge
sync/search.

The guarded helper for the Cloud identity portion is:

```bash
scripts/live-site-identity-provision.py \
  --output-dir .tmp/live-site-identity/npcink-live-identity
```

Default mode is prepare-only. It writes the internal service request plan for
account upsert, site provision, site activation, and site key issue. It does not
call the Cloud service.

After the exact approval text above is provided and
`MAGICK_CLOUD_INTERNAL_AUTH_TOKEN` is available, the identity step can be
executed with:

```bash
scripts/live-site-identity-provision.py \
  --execute \
  --approval-file .tmp/live-site-identity/npcink-identity-approval.txt \
  --base-url http://127.0.0.1:8010 \
  --output-dir .tmp/live-site-identity/npcink-live-identity
```

The execute report is redacted. If key issue succeeds, the customer-facing
Cloud API Key is written only to
`.tmp/live-site-identity/npcink-live-identity/cloud-api-key.secret.json`; do not
commit or paste that value into shared docs or terminal summaries.

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

Use the guarded rollback helper first:

```bash
scripts/live-site-addon-rollback.py \
  --snapshot .tmp/live-site-stage1/npcink-stage1/addon-install/prewrite-package/snapshot.json \
  --output-dir .tmp/live-site-addon-rollback/npcink-stage1
```

Default mode is prepare-only. It reads the pre-write snapshot, checks the target
URL/path and Local MySQL socket, writes a rollback plan, and does not mutate
WordPress.

Required approval text for execute mode:

```text
我明确批准在 npcink.local 回滚 Cloud addon 本地接入：停用 Cloud addon，
在预写快照显示原设置为空时删除 npcink_cloud_addon_settings；本次不导入数据库，
不运行 search-replace，不撤销 Cloud identity，不运行 runtime smoke，不运行 Site Knowledge，
不写内容，不启用 monitoring。
```

After the exact approval text is provided, execute with:

```bash
scripts/live-site-addon-rollback.py \
  --execute \
  --approval-file .tmp/live-site-addon-rollback/npcink-rollback-approval.txt \
  --snapshot .tmp/live-site-stage1/npcink-stage1/addon-install/prewrite-package/snapshot.json \
  --output-dir .tmp/live-site-addon-rollback/npcink-stage1
```

The helper only deactivates `magick-ai-cloud-addon`. It deletes
`npcink_cloud_addon_settings` only when the pre-write snapshot showed empty
addon settings. If the snapshot contained existing base URL, site ID, key, or
secret presence, it will not attempt to restore or delete that redacted state.

Cloud API key revocation is a separate Cloud service-plane/internal operation.
Do not run it through the public runtime surface.

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
