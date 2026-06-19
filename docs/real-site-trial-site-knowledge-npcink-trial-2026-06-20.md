# Real Site Trial Site Knowledge - npcink-trial - 2026-06-20

Status: bounded Site Knowledge rehearsal complete for `npcink-trial`.

Purpose: verify that the dedicated `site_npcink_trial` Cloud identity can
ingest a bounded public WordPress content subset, return evidence-backed
writing-support assistance, and preserve the Cloud boundary as runtime/detail
only.

## Scope And Boundary

- WordPress target: `/Users/muze/Local Sites/npcink-trial/app/public`
- Stored WordPress URL: `http://127.0.0.1:8099`
- Cloud base URL: `http://127.0.0.1:8010`
- Cloud site ID: `site_npcink_trial`
- Cloud account ID: `acct_site_npcink_trial`
- Cloud subscription ID: `sub_site_npcink_trial`
- WordPress source posture: read-only public `post` / `page` extraction
- Runtime write posture: `suggestion_only`
- Direct WordPress write: not used
- Direct publishing: not used
- Batch article generation: not used
- Cloud prompt/router/workflow editor: not used
- Cloud skill registry or MCP platform: not used

This remains a local clone/staging rehearsal. It is not a live customer trial
and does not authorize writes to `npcink.local`, `dbd.local`, `wp.local`, or
another live site.

## Configuration

Cloud Site Knowledge configuration at run time:

- Vector backend: `zilliz_cloud`
- Embedding provider: `tei`
- Embedding model: `BAAI/bge-m3`
- Embedding dimensions: `1024`
- Max sync documents per run: `500`
- Max sync chunks per run: `5000`
- Comment indexing enabled in Cloud config: `true`
- Rerank provider: `disabled`

This rehearsal did not send comments. Only public `post` and `page` documents
were supplied.

## Data Guard Finding

The first sync attempt used a broader public excerpt payload and was rejected
before execution:

- Error: `cloud_runtime_pii_classification_required`
- Message: runtime input appears to contain personal data and must use
  `data_classification=pii`

This was treated as a fail-closed safety result. The run was not forced through
as `pii`. Instead, the payload was reduced to a conservative public
title/summary subset, and a local dry check using Cloud's runtime data guard
returned no PII or secret finding before the successful sync.

## Source Content

The successful sync submitted 9 public WordPress documents:

- `AI 插件系列`
- `NavXia - AI智能驱动的高性能WordPress导航主题`
- `WPunion - 包含基础优化与功能增强等功能的WordPress 插件`
- `User Switching - 用户切换 WordPress 插件`
- `Polylang - WordPress 多语言插件`
- `Query Monitor - WordPress 的开发人员工具面板`
- `Image Clear - WordPress 图片清理插件`
- `Beebeework、比比工房主题 - 高仿小红书网页的 WordPress 主题`
- `Sample Page`

Only these fields were sent:

- `post_id`
- `post_type`
- `post_status`
- `title`
- `url`
- `modified_gmt`
- `excerpt`
- `content_excerpt`
- safe non-hash content ref

Drafts, private posts, comments, users, credentials, WordPress admin data, and
raw full post bodies were not sent.

## Site Knowledge Runtime Evidence

Sync run:

- Run ID: `run_cb5380d9aba34d58ac6e3a3c626fc3c8`
- Ability: `magick-ai-cloud/site-knowledge-sync`
- Status: succeeded
- Sync status: completed
- Sync mode: rebuild
- Submitted documents: 9
- Indexed documents: 9
- Indexed chunks: 9
- Skipped documents: 0
- Progress stage: completed
- Write posture: `suggestion_only`
- Direct WordPress write: false

Search run:

- Run ID: `run_318cd6d61b4642fd93549911c1945774`
- Ability: `magick-ai-cloud/site-knowledge-search`
- Intent: `writing_support_plan`
- Query: `WordPress AI 导航主题 多语言插件 开发调试工具 图片清理插件 写作准备`
- Status: succeeded
- Result count: 5
- Evidence gate: passed
- Evidence source count: 5
- Write posture: `suggestion_only`
- Direct WordPress write: false
- Provider ID: `site_knowledge`
- Model ID: `site-knowledge-managed`

Top search evidence:

- `AI 插件系列` (`post_id=280982`, score `0.7036`)
- `NavXia - AI智能驱动的高性能WordPress导航主题`
  (`post_id=280838`, score `0.6593`)
- `Polylang - WordPress 多语言插件` (`post_id=22057`, score `0.6357`)
- `Image Clear - WordPress 图片清理插件` (`post_id=280875`, score `0.6296`)
- `Query Monitor - WordPress 的开发人员工具面板`
  (`post_id=22055`, score `0.6177`)

The search response included a `site_knowledge_suggestion_agent` handoff with:

- `handoff_owner`: `wordpress_local`
- `requires_local_approval`: true
- `direct_wordpress_write`: false
- forbidden actions including `direct_wordpress_write`, `cloud_publish`,
  `cloud_workflow_truth`, `cloud_prompt_or_preset_truth`,
  `article_body_generation`, and `article_write_plan_generation`

Status run:

- Run ID: `run_0c36b9da127a487889a6ecbe41698067`
- Ability: `magick-ai-cloud/site-knowledge-status`
- Status: succeeded
- Index status: ready
- Indexed documents: 9
- Indexed chunks: 9
- Quota status: ok
- Document utilization: `0.0009`
- Write posture: `suggestion_only`
- Direct WordPress write: false

## Usage, Credit, And Billing Evidence

For the three successful Site Knowledge runs:

- Runs: 3
- Provider calls: 10
- Provider: `tei`
- Model: `tei/BAAI/bge-m3`
- Input / total tokens: 2066
- Output tokens: 0

Usage meter totals:

- `runs`: 3
- `provider_calls`: 10
- `tokens_in`: 2066
- `tokens_total`: 2066

AI credit ledger:

- Entries: 25
- Total credit delta: `-32`
- Rate version: `ai-credit-ledger-v2`
- Breakdown:
  - runs: `-3`
  - model tokens: `-10`
  - vector documents: `-18`
  - vector chunks: `-1`
  - other provider calls: `0`

After rebuilding billing detail for `sub_site_npcink_trial`, the latest
current-period billing snapshot covered both the earlier runtime smoke and this
Site Knowledge phase:

- Snapshot ID:
  `bill_site_npcink_trial_sub_site_npcink_trial_1781888169_1784480169`
- Generated at: `2026-06-19T17:16:25.850168+00:00`
- Billing totals:
  - `runs`: 4
  - `provider_calls`: 11
  - `tokens_in`: 2378
  - `tokens_out`: 10
  - `tokens_total`: 2388

These totals reconcile with:

- 1 previous read-only hosted runtime smoke run;
- 3 Site Knowledge runs;
- 1 previous text provider call;
- 10 Site Knowledge embedding/search provider calls.

## WordPress Content Verification

Published content counts remained consistent with preflight, setup, and runtime
smoke:

- public `post` / `page`: `1968`
- public `post`: `1967`
- public `page`: `1`

No WordPress posts, pages, taxonomies, users, menus, media records, or unrelated
options were changed by this Site Knowledge rehearsal.

## Go / No-Go

Decision: Site Knowledge phase passed for the `npcink-trial` clone.

Proven:

- `site_npcink_trial` can ingest a bounded public content subset;
- Site Knowledge search returns source-backed writing-support evidence;
- evidence gate passed;
- output stayed `suggestion_only`;
- WordPress write owner stayed `wordpress_local`;
- Cloud did not publish, mutate content, or become a control plane;
- usage, credit, and billing/detail evidence were recorded and reconciled;
- Cloud's data guard failed closed on a broader payload and the successful
  payload used a safer public summary subset.

Remaining limitations:

- This is still a local clone/staging rehearsal, not a live customer trial.
- The sync used 9 documents, not the full 1968 public post/page corpus.
- The content payload was intentionally conservative after data guard rejected
  a broader excerpt payload.
- No browser/admin UI review was performed in this pass.

## Next Safe Action

Prepare an operator go/no-go closeout for the real-site trial path:

1. summarize the full `npcink-trial` evidence chain from preflight through Site
   Knowledge;
2. decide whether the next target is a larger staging batch or a low-risk live
   site with second explicit approval;
3. preserve the no-write boundary unless a separate live-site approval is
   recorded.

Do not enable:

- direct publishing;
- article body generation;
- batch article generation;
- Cloud prompt/router/workflow editing;
- Cloud skill registry;
- MCP platform behavior;
- live-site writes without second approval.
