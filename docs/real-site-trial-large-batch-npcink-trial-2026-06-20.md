# Real Site Trial Large Batch - npcink-trial - 2026-06-20

Status: larger staging Site Knowledge batch passed.

Purpose: extend the `npcink-trial` clone evidence from a 9-document bounded
Site Knowledge rehearsal to a 100-document staging batch while preserving the
same Cloud/WordPress boundary.

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

The batch used 100 public WordPress documents:

- source post types: `post`, `page`
- source statuses: `publish`
- document split: 99 posts, 1 page
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
  `npcink-trial-largebatch-doc-<post_id>-v1`, not SHA-like values;
- local Cloud runtime data guard dry check returned no PII or secret finding;
- Site Knowledge contract validation passed before execution.

The runtime input file was kept local-only under:

```text
/Users/muze/gitee/npcink-cloud/.tmp/npcink-trial-large-batch-20260620/sync-payload.json
```

## Sync Evidence

The sync was submitted through the verified WordPress Cloud addon runtime
client. It used `sync_mode=rebuild`, so the previous 9-document trial index was
replaced by this 100-document staging index in Cloud.

- Run ID: `run_722d6f50f10049578d68b4de24afd36c`
- Ability: `npcink-cloud/site-knowledge-sync`
- Contract: `site_knowledge_sync.v1`
- Status: succeeded
- Sync status: completed
- Sync mode: rebuild
- Accepted documents: 100
- Indexed documents: 100
- Indexed chunks: 167
- Failed documents: 0
- Truncated documents: 0
- Skipped documents: 0
- Skipped due to quota: 0
- Deleted previous index entries: 18
- Write posture: `suggestion_only`
- Direct WordPress write: false

Quota after sync:

- indexed documents: 100
- indexed chunks: 167
- document utilization: `0.01`
- chunk utilization: `0.0008`
- quota status: ok

## Search Evidence

The search was submitted through the verified addon client after the rebuild.

- Run ID: `run_6426cc25e4954ffa836a05ebddd06691`
- Ability: `npcink-cloud/site-knowledge-search`
- Contract: `site_knowledge_search.v1`
- Intent: `writing_support_plan`
- Query:
  `WordPress AI 插件 导航主题 多语言 图片清理 开发调试工具 写作准备`
- Status: succeeded
- Result status: ready
- Result count: 8
- Evidence gate: passed
- Evidence source count: 8
- Minimum score: `0.2`
- Required sources: 3
- No-hit policy: `abstain`
- Write posture: `suggestion_only`
- Direct WordPress write: false
- Handoff owner: `wordpress_local`
- Requires local approval: true

Top sources:

- `MagicPost - WordPress 文章管理增强插件` (`post_id=21951`, score `0.6951`)
- `AI内容生成器 - WordPress AI 内容生成插件`
  (`post_id=279790`, score `0.6853`)
- `AI 插件系列` (`post_id=280982`, score `0.6843`)
- `WP AI Reader - WordPress AI 导读插件` (`post_id=278400`, score `0.6804`)
- `WP AI Reader - WordPress AI 导读插件` (`post_id=278400`, score `0.6794`)
- `AI导读 - WordPress AI 内容生成插件` (`post_id=279803`, score `0.6787`)
- `NavXia - AI智能驱动的高性能WordPress导航主题`
  (`post_id=280838`, score `0.6781`)
- `WPTurbo - WordPress 新能优化插件` (`post_id=22058`, score `0.6698`)

The duplicate `WP AI Reader` source reflects multiple indexed chunks for the
same public post, not multiple WordPress writes.

The response's handoff retained these boundaries:

- `handoff_owner`: `wordpress_local`
- `requires_local_approval`: true
- `direct_wordpress_write`: false
- forbidden outputs included direct WordPress write, Cloud publish, article
  body, article title, SEO copy, article write plan, full article draft, and
  ready-to-publish content.

## Status Evidence

The status check was submitted through the verified addon client after search.

- Run ID: `run_ceec2f6be1b04ce98ba10d5fee10ecbd`
- Ability: `npcink-cloud/site-knowledge-status`
- Contract: `site_knowledge_status.v1`
- Status: succeeded
- Index status: ready
- Indexed posts/documents: 100
- Indexed chunks: 167
- Truncated documents: 0
- Quota status: ok
- Document utilization: `0.01`
- Chunk utilization: `0.0008`
- Write posture: `suggestion_only`
- Direct WordPress write: false

## Usage, Credit, And Billing Evidence

After this larger batch and a billing snapshot rebuild, the cumulative
`site_npcink_trial` evidence totals were:

- Runs: 7
- Provider calls: 179
- Tokens in: 68468
- Tokens out: 10
- Tokens total: 68478
- Credit ledger entries: 369
- Total credit delta: `-422`

Latest billing snapshot:

- Snapshot ID:
  `bill_site_npcink_trial_sub_site_npcink_trial_1781888169_1784480169`
- Generated at: `2026-06-19T17:31:18.018881+00:00`
- Billing totals:
  - `runs`: 7
  - `provider_calls`: 179
  - `tokens_in`: 68468
  - `tokens_out`: 10
  - `tokens_total`: 68478

Billing breakdown:

- `knowledge`: 6 runs, 178 provider calls, 68156 total tokens
- `text`: 1 run, 1 provider call, 322 total tokens

The latest billing totals reconcile with:

- the earlier read-only hosted runtime smoke;
- the earlier 9-document Site Knowledge sync/search/status;
- this 100-document Site Knowledge rebuild/search/status.

## WordPress Content Verification

Published content counts remained consistent:

- public `post` / `page`: `1968`
- public `post`: `1967`
- public `page`: `1`

No WordPress posts, pages, taxonomies, users, menus, media records, or unrelated
options were changed by this large-batch rehearsal.

## Decision

Decision: larger staging batch passed.

Proven by this phase:

- `npcink-trial` can run a 100-document public Site Knowledge rebuild through
  the verified addon client;
- Cloud index status remains ready after the larger batch;
- evidence-backed writing support still passes the evidence gate;
- handoff remains WordPress-local and approval-gated;
- usage, credit, and billing detail can be refreshed and reconciled;
- WordPress content remains unchanged.

Remaining limitations:

- This is still a local clone/staging rehearsal, not a live customer trial.
- The batch covered 100 of 1968 public posts/pages, not the full corpus.
- Comments were intentionally excluded.
- The search result can include multiple chunks from the same post.
- This does not prove full-corpus or live-site PII posture.

## Next Safe Action

The next safe action is not live execution by default.

Recommended next phase:

1. run a second larger staging batch, for example 300 to 500 public documents,
   still excluding comments and private/admin data;
2. keep `suggestion_only` and `direct_wordpress_write=false`;
3. record data guard, sync/search/status, usage, credit, billing, and WordPress
   content-count evidence;
4. only after that, prepare a separate live-site preflight.

Live-site execution remains no-go until a second explicit approval names the
exact live site and a fresh live backup/rollback plan is recorded.
