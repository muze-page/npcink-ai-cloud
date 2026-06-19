# Real Site Trial 300 Batch - npcink-trial - 2026-06-20

Status: 300-document staging Site Knowledge batch passed with bounded runtime
payload splitting.

Purpose: extend the `npcink-trial` clone evidence from 100 public WordPress
documents to 300 public WordPress documents while preserving the same
Cloud/WordPress boundary and public runtime payload limits.

## Scope And Boundary

- WordPress target: `/Users/muze/Local Sites/npcink-trial/app/public`
- Stored WordPress URL: `http://127.0.0.1:8099`
- Cloud base URL: `http://127.0.0.1:8010`
- Cloud site ID: `site_npcink_trial`
- Cloud account ID: `acct_site_npcink_trial`
- Cloud subscription ID: `sub_site_npcink_trial`
- Source posture: read-only public `post` / `page` extraction
- Runtime write posture: `suggestion_only`
- Direct WordPress write: not used
- Direct publishing: not used
- Batch article generation: not used
- Cloud prompt/router/workflow editor: not used
- Cloud skill registry or MCP platform: not used

This remains a local clone/staging rehearsal. It is not a live customer trial
and does not authorize writes to `npcink.local`, `dbd.local`, `wp.local`, or
another live site.

## Input Preparation

The staging input selected 300 public WordPress documents:

- source post types: `post`, `page`
- source statuses: `publish`
- intended document split after indexing: 299 posts, 1 page
- comments: not included
- drafts/private/pending/future posts: not included
- users, author email, IP addresses, user agents, admin metadata, credentials:
  not included

Payload fields sent per document:

- `post_id`
- `post_type`
- `post_status`
- `title`
- `url`
- `modified_gmt`
- `excerpt`
- `content_excerpt`
- stable non-hash `content_hash` ref

Payload hardening:

- public text was stripped of markup and shortcodes;
- obvious email, phone-number, and ID-card-like patterns were replaced before
  the runtime payload was sent;
- `content_hash` used stable refs such as
  `npcink-trial-300batch-doc-<post_id>-v1`, not SHA-like values;
- Cloud runtime data guard dry checks returned no PII or secret finding;
- Site Knowledge contract validation passed before execution;
- runtime schema validation passed for the split payloads.

Local-only payload files:

```text
/Users/muze/gitee/magick-ai-cloud/.tmp/npcink-trial-300-batch-20260620/sync-payload.json
/Users/muze/gitee/magick-ai-cloud/.tmp/npcink-trial-300-batch-20260620/sync-rebuild-200-payload.json
/Users/muze/gitee/magick-ai-cloud/.tmp/npcink-trial-300-batch-20260620/sync-refresh-100-payload.json
```

## Payload Bound Finding

A single 300-document runtime payload was rejected before execution:

- error code: `cloud_runtime_failed`
- message: `body: Value error, input contains too many items`
- root cause: public runtime payload bound `MAX_RUNTIME_LIST_ITEMS=200`

This was treated as a correct fail-closed boundary. The limit was not widened.
The 300-document batch was instead executed as two bounded runtime calls:

1. 200-document `rebuild`
2. 100-document `refresh`

## Sync Evidence

### Rebuild 200

- Run ID: `run_dfc84176526e40da90383fd198e4f7e3`
- Ability: `magick-ai-cloud/site-knowledge-sync`
- Contract: `site_knowledge_sync.v1`
- Status: succeeded
- Sync status: completed
- Sync mode: rebuild
- Accepted documents: 200
- Indexed documents: 200
- Indexed chunks: 299
- Failed documents: 0
- Truncated documents: 0
- Skipped documents: 0
- Skipped due to quota: 0
- Deleted previous index entries: 267
- Write posture: `suggestion_only`
- Direct WordPress write: false

### Refresh 100

- Run ID: `run_7207e3416d854087be485ce97c363aac`
- Ability: `magick-ai-cloud/site-knowledge-sync`
- Contract: `site_knowledge_sync.v1`
- Status: succeeded
- Sync status: completed
- Sync mode: refresh
- Accepted documents: 100
- Indexed documents: 100
- Indexed chunks: 117
- Failed documents: 0
- Truncated documents: 0
- Skipped documents: 0
- Skipped due to quota: 0
- Deleted previous index entries: 0
- Write posture: `suggestion_only`
- Direct WordPress write: false

Cloud index after both sync runs:

- indexed documents: 300
- indexed chunks: 416
- document utilization: `0.03`
- chunk utilization: `0.0021`
- quota status: ok

## Search Evidence

The search was submitted through the verified WordPress Cloud addon runtime
client after the two sync runs.

- Run ID: `run_28cceb62161e4cddaef13ffa7093910f`
- Ability: `magick-ai-cloud/site-knowledge-search`
- Contract: `site_knowledge_search.v1`
- Intent: `writing_support_plan`
- Query:
  `WordPress AI 插件 导航主题 多语言 图片清理 开发调试工具 写作准备 网盘 主题 插件`
- Status: succeeded
- Result status: ready
- Result count: 10
- Evidence gate: passed
- Evidence source count: 10
- Minimum score: `0.2`
- Required sources: 3
- No-hit policy: `abstain`
- Write posture: `suggestion_only`
- Direct WordPress write: false
- Handoff owner: `wordpress_local`
- Requires local approval: true

Top sources:

- `MagicPost - WordPress 文章管理增强插件` (`post_id=21951`, score `0.7165`)
- `NavXia - AI智能驱动的高性能WordPress导航主题`
  (`post_id=280838`, score `0.7043`)
- `Query Monitor - WordPress 的开发人员工具面板`
  (`post_id=22055`, score `0.6984`)
- `AI 插件系列` (`post_id=280982`, score `0.6942`)
- `WP AI Reader - WordPress AI 导读插件` (`post_id=278400`, score `0.6862`)
- `Halo - 强大易用的开源建站工具` (`post_id=277152`, score `0.6820`)
- `WPTurbo - WordPress 新能优化插件` (`post_id=22058`, score `0.6787`)
- `AI导读 - WordPress AI 内容生成插件` (`post_id=279803`, score `0.6782`)
- `AIYA-CMS - WordPress 多功能CMS主题` (`post_id=277783`, score `0.6688`)
- `WP Magick Toolbox（魔法工具箱） - WordPress 综合优化增强插件`
  (`post_id=277510`, score `0.6589`)

The response retained these boundaries:

- `handoff_owner`: `wordpress_local`
- `requires_local_approval`: true
- `write_posture`: `suggestion_only`
- `direct_wordpress_write`: false

## Status Evidence

The status check was submitted through the verified addon client after search.

- Run ID: `run_ecaa488de2ef4453a7a75fc7590dcb64`
- Ability: `magick-ai-cloud/site-knowledge-status`
- Contract: `site_knowledge_status.v1`
- Status: succeeded
- Index status: ready
- Indexed posts/documents: 300
- Indexed chunks: 416
- Truncated documents: 0
- Has stale content: false
- Quota status: ok
- Document utilization: `0.03`
- Chunk utilization: `0.0021`
- Write posture: `suggestion_only`
- Direct WordPress write: false

## Usage, Credit, And Billing Evidence

After this 300-document batch and billing snapshot rebuild, cumulative
`site_npcink_trial` evidence totals were:

- Runs: 11
- Provider calls: 596
- Tokens in: 201318
- Tokens out: 10
- Tokens total: 201328
- Credit ledger entries: 1211
- Total credit delta: `-1485`

Latest billing snapshot:

- Snapshot ID:
  `bill_site_npcink_trial_sub_site_npcink_trial_1781888169_1784480169`
- Generated at: `2026-06-19T17:41:08.805993+00:00`
- Billing totals:
  - `runs`: 11
  - `provider_calls`: 596
  - `tokens_in`: 201318
  - `tokens_out`: 10
  - `tokens_total`: 201328

Billing breakdown:

- `knowledge`: 10 runs, 595 provider calls, 201006 total tokens
- `text`: 1 run, 1 provider call, 322 total tokens

Run record totals for this site:

- `npcink.runtime_smoke`: 1 succeeded
- `magick-ai-cloud/site-knowledge-sync`: 4 succeeded
- `magick-ai-cloud/site-knowledge-search`: 3 succeeded
- `magick-ai-cloud/site-knowledge-status`: 3 succeeded

## WordPress Content Verification

Published content counts remained consistent:

- public `post` / `page`: `1968`
- public `post`: `1967`
- public `page`: `1`

No WordPress posts, pages, taxonomies, users, menus, media records, or unrelated
options were changed by this 300-document staging rehearsal.

## Decision

Decision: 300-document staging batch passed.

Proven by this phase:

- 300 public WordPress documents can be indexed under the dedicated
  `site_npcink_trial` Cloud identity using bounded runtime calls;
- Cloud's runtime payload item limit fails closed and can be respected through
  staged sync calls;
- Site Knowledge remains searchable and evidence-gated after the larger batch;
- handoff remains WordPress-local and approval-gated;
- usage, credit, and billing detail can be refreshed and reconciled;
- WordPress content remains unchanged.

Remaining limitations:

- This is still a local clone/staging rehearsal, not a live customer trial.
- The batch covered 300 of 1968 public posts/pages, not the full corpus.
- Comments were intentionally excluded.
- The public runtime list-item bound means larger staging batches must be
  chunked into calls of at most 200 documents.
- This does not prove full-corpus or live-site PII posture.

## Next Safe Action

Recommended next phase:

1. run a 500-document staging proof as `200 rebuild + 200 refresh + 100 refresh`;
2. keep public `post/page` only and continue excluding comments/private/admin
   data;
3. keep `suggestion_only` and `direct_wordpress_write=false`;
4. record data guard, runtime payload-bound, sync/search/status, usage, credit,
   billing, and WordPress content-count evidence;
5. after the 500-document staging proof, prepare a separate read-only live-site
   preflight.

Live-site execution remains no-go until a second explicit approval names the
exact live site and a fresh live backup/rollback plan is recorded.
