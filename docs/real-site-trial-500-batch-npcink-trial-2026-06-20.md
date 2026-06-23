# Real Site Trial 500 Batch - npcink-trial - 2026-06-20

Status: 500-document staging Site Knowledge batch passed.

Purpose: extend the `npcink-trial` clone evidence from 300 public WordPress
documents to 500 public WordPress documents while preserving Cloud as
runtime/detail/evidence only and WordPress as the final control/write owner.

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

The staging input selected 500 public WordPress documents:

- source post types: `post`, `page`
- source statuses: `publish`
- final indexed split: 499 posts, 1 page
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
  `npcink-trial-500batch-doc-<post_id>-v1`, not SHA-like values;
- Cloud runtime data guard dry checks returned no PII or secret finding;
- Site Knowledge contract validation passed before execution;
- runtime schema validation passed for each split payload.

Local-only payload files:

```text
/Users/muze/gitee/npcink-cloud/.tmp/npcink-trial-500-batch-20260620/sync-payload.json
/Users/muze/gitee/npcink-cloud/.tmp/npcink-trial-500-batch-20260620/sync-rebuild-200-payload.json
/Users/muze/gitee/npcink-cloud/.tmp/npcink-trial-500-batch-20260620/sync-refresh-200-payload.json
/Users/muze/gitee/npcink-cloud/.tmp/npcink-trial-500-batch-20260620/sync-refresh-100-payload.json
```

## Payload Bound Handling

The previous 300-document phase proved the public runtime list-item bound:

- `MAX_RUNTIME_LIST_ITEMS=200`
- larger public runtime payloads must be split
- the bound was not widened for this phase

The 500-document batch therefore used:

1. 200-document `rebuild`
2. 200-document `refresh`
3. 100-document `refresh`

All three payloads passed runtime schema validation before execution.

## Sync Evidence

### Rebuild 200

- Run ID: `run_f3d650edda3f46578649924b4283c886`
- Ability: `npcink-cloud/site-knowledge-sync`
- Contract: `site_knowledge_sync.v1`
- Status: succeeded
- Sync status: completed
- Sync mode: rebuild
- Accepted documents: 200
- Indexed documents: 200
- Indexed chunks: 268
- Failed documents: 0
- Truncated documents: 0
- Skipped documents: 0
- Skipped due to quota: 0
- Deleted previous index entries: 716
- Write posture: `suggestion_only`
- Direct WordPress write: false

### Refresh 200

- Run ID: `run_51790f57f9494dc0b23164d1b84979ca`
- Ability: `npcink-cloud/site-knowledge-sync`
- Contract: `site_knowledge_sync.v1`
- Status: succeeded
- Sync status: completed
- Sync mode: refresh
- Accepted documents: 200
- Indexed documents: 200
- Indexed chunks: 210
- Failed documents: 0
- Truncated documents: 0
- Skipped documents: 0
- Skipped due to quota: 0
- Deleted previous index entries: 0
- Write posture: `suggestion_only`
- Direct WordPress write: false

### Refresh 100

- Run ID: `run_3239e1e6a3de4629a9983321ad517410`
- Ability: `npcink-cloud/site-knowledge-sync`
- Contract: `site_knowledge_sync.v1`
- Status: succeeded
- Sync status: completed
- Sync mode: refresh
- Accepted documents: 100
- Indexed documents: 100
- Indexed chunks: 102
- Failed documents: 0
- Truncated documents: 0
- Skipped documents: 0
- Skipped due to quota: 0
- Deleted previous index entries: 0
- Write posture: `suggestion_only`
- Direct WordPress write: false

Cloud index after all sync runs:

- indexed documents: 500
- indexed chunks: 580
- document utilization: `0.05`
- chunk utilization: `0.0029`
- quota status: ok

## Search Evidence

The search was submitted through the verified WordPress Cloud addon runtime
client after the three sync runs.

- Run ID: `run_258c6ded79ad44f7ab01eba5f522aa7e`
- Ability: `npcink-cloud/site-knowledge-search`
- Contract: `site_knowledge_search.v1`
- Intent: `writing_support_plan`
- Query:
  `WordPress AI 插件 导航主题 多语言 图片清理 开发调试工具 写作准备 网盘 主题 插件 邮箱 教程`
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

- `MagicPost - WordPress 文章管理增强插件` (`post_id=21951`, score `0.7168`)
- `NavXia - AI智能驱动的高性能WordPress导航主题`
  (`post_id=280838`, score `0.7144`)
- `WP AI Reader - WordPress AI 导读插件` (`post_id=278400`, score `0.7083`)
- `WP AI Reader - WordPress AI 导读插件` (`post_id=278400`, score `0.7007`)
- `WPTurbo - WordPress 新能优化插件` (`post_id=22058`, score `0.6960`)
- `AI 插件系列` (`post_id=280982`, score `0.6943`)
- `Pure Blog - 极简免费WordPress博客主题` (`post_id=18441`, score `0.6873`)
- `AI导读 - WordPress AI 内容生成插件` (`post_id=279803`, score `0.6870`)
- `Query Monitor - WordPress 的开发人员工具面板`
  (`post_id=22055`, score `0.6861`)
- `mkBlog - 简约的WordPress博客主题` (`post_id=18920`, score `0.6818`)

The duplicate `WP AI Reader` source reflects multiple indexed chunks for the
same public post, not multiple WordPress writes.

The response retained these boundaries:

- `handoff_owner`: `wordpress_local`
- `requires_local_approval`: true
- `write_posture`: `suggestion_only`
- `direct_wordpress_write`: false

## Status Evidence

The status check was submitted through the verified addon client after search.

- Run ID: `run_200f694f33fa47338e96e9aa49df00c1`
- Ability: `npcink-cloud/site-knowledge-status`
- Contract: `site_knowledge_status.v1`
- Status: succeeded
- Index status: ready
- Indexed posts/documents: 500
- Indexed chunks: 580
- Truncated documents: 0
- Has stale content: false
- Quota status: ok
- Document utilization: `0.05`
- Chunk utilization: `0.0029`
- Write posture: `suggestion_only`
- Direct WordPress write: false

## Usage, Credit, And Billing Evidence

After this 500-document batch and billing snapshot rebuild, cumulative
`site_npcink_trial` evidence totals were:

- Runs: 16
- Provider calls: 1177
- Tokens in: 380034
- Tokens out: 10
- Tokens total: 380044
- Credit ledger entries: 2384
- Total credit delta: `-3130`

Latest billing snapshot:

- Snapshot ID:
  `bill_site_npcink_trial_sub_site_npcink_trial_1781888169_1784480169`
- Generated at: `2026-06-19T17:51:27.660397+00:00`
- Billing totals:
  - `runs`: 16
  - `provider_calls`: 1177
  - `tokens_in`: 380034
  - `tokens_out`: 10
  - `tokens_total`: 380044

Billing breakdown:

- `knowledge`: 15 runs, 1176 provider calls, 379722 total tokens
- `text`: 1 run, 1 provider call, 322 total tokens

Run record totals for this site:

- `npcink.runtime_smoke`: 1 succeeded
- `npcink-cloud/site-knowledge-sync`: 7 succeeded
- `npcink-cloud/site-knowledge-search`: 4 succeeded
- `npcink-cloud/site-knowledge-status`: 4 succeeded

## WordPress Content Verification

Published content counts remained consistent:

- public `post` / `page`: `1968`
- public `post`: `1967`
- public `page`: `1`

No WordPress posts, pages, taxonomies, users, menus, media records, or unrelated
options were changed by this 500-document staging rehearsal.

## Decision

Decision: 500-document staging batch passed.

Proven by this phase:

- 500 public WordPress documents can be indexed under the dedicated
  `site_npcink_trial` Cloud identity using bounded runtime calls;
- the public runtime payload limit remains respected without expanding Cloud
  ingress;
- Site Knowledge remains searchable and evidence-gated after the larger batch;
- handoff remains WordPress-local and approval-gated;
- usage, credit, and billing detail can be refreshed and reconciled;
- WordPress content remains unchanged.

Remaining limitations:

- This is still a local clone/staging rehearsal, not a live customer trial.
- The batch covered 500 of 1968 public posts/pages, not the full corpus.
- Comments were intentionally excluded.
- Larger staging batches must continue using calls of at most 200 documents.
- This does not prove full-corpus or live-site PII posture.

## Next Safe Action

Recommended next phase:

1. prepare a live-site preflight package, read-only only;
2. name the exact live candidate site before any live execution;
3. collect fresh live backup and rollback evidence;
4. sample live content categories and PII posture;
5. decide whether live should use a dedicated Cloud identity distinct from
   `site_npcink_trial`;
6. keep live runtime and Site Knowledge execution no-go until second explicit
   approval.

Do not proceed to live sync, live runtime smoke, direct publishing, or any
WordPress write from Cloud without that separate approval.
