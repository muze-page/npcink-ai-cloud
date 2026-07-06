# Real Site Trial Runtime Smoke - npcink-trial - 2026-06-20

Status: runtime smoke complete; Site Knowledge sync not started.

Purpose: verify that the `npcink-trial` clone can execute one minimal
read-only hosted runtime request through the verified WordPress Cloud addon,
and that Cloud run, provider-call, usage, credit, entitlement, and billing
detail evidence all remain isolated under the dedicated `site_npcink_trial`
identity.

## Scope And Boundary

- WordPress target: `/Users/muze/Local Sites/npcink-trial/app/public`
- Stored WordPress URL: `http://127.0.0.1:8099`
- Cloud base URL: `http://127.0.0.1:8010`
- Cloud site ID: `site_npcink_trial`
- Cloud account ID: `acct_site_npcink_trial`
- Cloud subscription ID: `sub_site_npcink_trial`
- Cloud role: hosted runtime, usage, credit, billing/detail, and evidence
- WordPress role: local control plane and final write owner
- Direct WordPress publishing: not used
- WordPress post/page mutation: not used
- Site Knowledge sync/search/status: not run
- Batch article generation: not used
- Cloud prompt/router/workflow editor: not used
- Cloud skill registry or MCP platform: not used

This remains a local clone/staging rehearsal. It is not a live customer trial
and does not authorize writes to `npcink.local`, `dbd.local`, `wp.local`, or
another live site.

Historical ID note: this document records the old Free package ID
`plan_free_v1`; current package records use `free` / `free_v1`.

## Pre-Smoke Baseline

Before the runtime smoke, the dedicated `site_npcink_trial` evidence baseline
was empty:

- `run_records`: 0
- `usage_meter_events`: 0
- `provider_call_records` for this site's runs: 0
- `credit_ledger_entries`: 0
- `billing_snapshots`: 0
- `site_knowledge_documents`: 0
- `site_knowledge_chunks`: 0

## Runtime Request

The request was sent through the verified addon PHP runtime client:

- helper: `npcink_cloud_addon_verified_runtime_client()`
- method: `execute_runtime(...)`
- ability: `npcink.runtime_smoke`
- ability family: `text`
- contract version: `npcink-runtime-smoke.v1`
- channel: `wp_cli_trial`
- execution kind: `text`
- execution pattern: `inline`
- data classification: `public`
- storage mode: `result_only`
- fallback allowed: true
- trace request label: `trace_npcink_trial_runtime_smoke_20260620_001`
- idempotency key: `idem_npcink_trial_runtime_smoke_20260620_001`

The prompt asked for a fixed short response only:

```text
Reply with exactly: npcink trial runtime smoke ok
```

No site content, post body, customer data, credential, or WordPress write
instruction was sent.

## Runtime Result

The hosted runtime request succeeded:

- Run ID: `run_b63ebed3af65480a91f7c4ee2188c93d`
- Status: succeeded
- Trace ID: `314cd2f8fb2b046f29f16d7bf6e8cce2`
- Provider ID: `openai`
- Model ID: `gpt-5.5`
- Instance ID: `openai-global-gpt-5-5`
- Fallback used: false
- Provider call count: 1
- Output preview: `npcink trial runtime smoke ok`

The persisted run belongs to the dedicated trial identity:

- `site_id`: `site_npcink_trial`
- `account_id`: `acct_site_npcink_trial`
- `subscription_id`: `sub_site_npcink_trial`
- `plan_version_id`: `plan_free_v1`

## Provider And Usage Evidence

Provider call evidence:

- Provider calls: 1
- Input tokens: 312
- Output tokens: 10
- Total tokens: 322
- Provider call latency: 2364 ms

Usage meter events:

- `runs`: 1
- `provider_calls`: 1
- `tokens_in`: 312
- `tokens_out`: 10
- `tokens_total`: 322

All usage events were recorded under:

- `site_id`: `site_npcink_trial`
- `account_id`: `acct_site_npcink_trial`
- `subscription_id`: `sub_site_npcink_trial`
- `plan_version_id`: `plan_free_v1`
- `ability_family`: `text`
- `channel`: `wp_cli_trial`
- `execution_kind`: `text`
- `execution_tier`: `cloud`
- `data_classification`: `public`

## Credit Evidence

AI credit ledger entries were created under `acct_site_npcink_trial`:

- Entries: 3
- Total credit delta: `-2`
- Rate version: `ai-credit-ledger-v2`
- Breakdown:
  - hosted run: `-1`
  - model tokens: `-1`
  - provider call count: `0`

All credit ledger entries reference
`run_b63ebed3af65480a91f7c4ee2188c93d`.

## Billing Detail Evidence

After runtime execution, the existing service-plane billing rebuild path was
called for `sub_site_npcink_trial` to materialize current-period billing detail.

Billing rebuild result:

- Status: refreshed
- Site count: 1
- Snapshot ID:
  `bill_site_npcink_trial_sub_site_npcink_trial_1781888169_1784480169`
- Generated at: `2026-06-19T17:09:50.471505+00:00`

Billing totals matched runtime usage:

- `runs`: 1
- `provider_calls`: 1
- `tokens_in`: 312
- `tokens_out`: 10
- `tokens_total`: 322

## WordPress Content Verification

Published content counts remained consistent with preflight and setup:

- public `post` / `page`: `1968`
- public `post`: `1967`
- public `page`: `1`

No WordPress posts, pages, taxonomies, users, menus, media records, or
unrelated options were changed by this runtime smoke.

## Site Knowledge Verification

Site Knowledge was intentionally not started in this phase.

Post-smoke counts remained:

- `site_knowledge_documents`: 0
- `site_knowledge_chunks`: 0

## Go / No-Go

Decision: runtime smoke phase passed.

Proven:

- addon-to-Cloud hosted runtime execution works for `npcink-trial`;
- runtime evidence is isolated under `site_npcink_trial`;
- provider call, usage meter, credit ledger, and billing detail reconcile;
- WordPress content remained unchanged;
- Site Knowledge was not accidentally started.

Remaining before the final real-site validation path is complete:

- Site Knowledge sync against bounded public content;
- Site Knowledge search with evidence-backed `suggestion_only` result;
- Site Knowledge status/metrics verification;
- operator go/no-go record for whether this clone is ready to represent the
  real-site trial path.

## Next Safe Action

After explicit approval, run the next bounded phase:

1. sync a bounded public `post` / `page` subset for `site_npcink_trial`;
2. search Site Knowledge for one reviewable writing-support question;
3. verify `suggestion_only` output and `direct_wordpress_write=false`;
4. stop and record the result.

Do not enable:

- direct publishing;
- article body generation;
- batch article generation;
- Cloud prompt/router/workflow editing;
- Cloud skill registry;
- MCP platform behavior;
- live-site writes.
