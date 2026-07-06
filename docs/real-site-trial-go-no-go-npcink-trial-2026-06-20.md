# Real Site Trial Go/No-Go Closeout - npcink-trial - 2026-06-20

Status: go for a larger staging batch; no-go for live-site execution without a
second explicit live approval.

Purpose: close the `npcink-trial` real-site clone evidence chain and decide the
next safe step toward proving Npcink AI Cloud as a WordPress hosted AI runtime
enhancement layer.

Historical ID note: this document records the old Free package IDs
`plan_free` / `plan_free_v1`; current package records use `free` / `free_v1`.

## Final Objective

The objective is not to expand the Cloud product surface. The objective is to
prove that Npcink AI Cloud can safely operate beside a real WordPress site as:

- hosted runtime;
- Site Knowledge runtime/detail;
- usage, credit, billing, entitlement, and run evidence;
- suggestion-only assistance for WordPress-local review.

Cloud must not become the final WordPress control plane, a publishing surface,
a second ability/workflow/router/prompt registry, or a direct WordPress write
owner.

## Evidence Chain

The `npcink-trial` path now has a staged evidence chain:

- `c3b042b` - `docs/real-site-trial-preflight-npcink-trial-2026-06-20.md`
- `0921d55` - `docs/real-site-trial-setup-npcink-trial-2026-06-20.md`
- `ab5528b` - `docs/real-site-trial-runtime-smoke-npcink-trial-2026-06-20.md`
- `439c566` - `docs/real-site-trial-site-knowledge-npcink-trial-2026-06-20.md`

Supporting package:

- `7cfecb0` - `docs/real-site-trial-package-2026-06-20.md`

## Boundary Result

The trial preserved the intended ownership split:

- WordPress remained the local control plane and final write owner.
- Cloud remained runtime, detail, metering, billing, and evidence.
- Site Knowledge output remained `suggestion_only`.
- Search handoff owner remained `wordpress_local`.
- `requires_local_approval` remained true.
- `direct_wordpress_write` remained false.

The trial did not introduce or use:

- direct publishing;
- post, page, taxonomy, user, menu, or media mutation;
- article body generation;
- batch article generation;
- Cloud prompt/router/workflow editing;
- Cloud ability registry;
- Cloud MCP platform;
- second scheduler or second workflow truth;
- new infrastructure outside the existing FastAPI, Postgres, Redis, worker,
  Docker Compose stack.

## Rollback And Setup Evidence

Before the one intended WordPress option write, rollback artifacts were saved
outside Git:

```text
/Users/muze/gitee/npcink-cloud/.tmp/npcink-trial-setup-20260620/npcink_cloud_addon_settings-before-20260619165455.json
/Users/muze/gitee/npcink-cloud/.tmp/npcink-trial-setup-20260620/npcink-trial-db-before-20260619165535.sql
```

Only one intended WordPress write was performed:

- option: `npcink_cloud_addon_settings`
- previous Cloud site: `site_npcink_local`
- new Cloud site: `site_npcink_trial`

No WordPress content object or unrelated option was changed by the setup,
runtime smoke, or Site Knowledge phases.

Current addon state, redacted:

```json
{
  "base_url": "http://127.0.0.1:8010",
  "site_id": "site_npcink_trial",
  "timeout": 8,
  "verified": true,
  "verified_at": "2026-06-19 16:56:58 UTC",
  "last_verification_error": "",
  "monitoring_enabled": true,
  "key_id": "[REDACTED_SECRET]",
  "secret": "[REDACTED_SECRET]"
}
```

## Current Cloud State

Current read-only Cloud DB snapshot for `site_npcink_trial`:

- site status: `active`
- account: `acct_site_npcink_trial`
- subscription: `sub_site_npcink_trial`
- subscription status: `active`
- plan: `plan_free`
- plan version: `plan_free_v1`

Run records:

- `npcink.runtime_smoke`: 1 succeeded
- `npcink-cloud/site-knowledge-sync`: 1 succeeded
- `npcink-cloud/site-knowledge-search`: 1 succeeded
- `npcink-cloud/site-knowledge-status`: 1 succeeded

Usage totals:

- `runs`: 4
- `provider_calls`: 11
- `tokens_in`: 2378
- `tokens_out`: 10
- `tokens_total`: 2388

Credit ledger:

- entries: 28
- total credit delta: `-34`

Billing snapshot:

- snapshot:
  `bill_site_npcink_trial_sub_site_npcink_trial_1781888169_1784480169`
- generated at: `2026-06-19T17:16:25.850168+00:00`
- totals reconcile with the 4 run records and usage meter totals.

Site Knowledge index:

- documents: 9
- chunks: 9

## Runtime Evidence

Runtime smoke succeeded through the verified addon client:

- run: `run_b63ebed3af65480a91f7c4ee2188c93d`
- ability: `npcink.runtime_smoke`
- provider: `openai`
- model: `gpt-5.5`
- instance: `openai-global-gpt-5-5`
- result preview: `npcink trial runtime smoke ok`
- usage: 1 run, 1 provider call, 312 input tokens, 10 output tokens
- credit delta: `-2`

The smoke prompt did not include site content, customer data, credentials, or
WordPress write instructions.

## Site Knowledge Evidence

The first broader public excerpt payload was rejected before execution:

- error: `cloud_runtime_pii_classification_required`
- decision: do not force it through as `pii`
- mitigation: reduce to a conservative public title/summary subset and dry
  check the payload before successful sync

Successful bounded sync:

- run: `run_cb5380d9aba34d58ac6e3a3c626fc3c8`
- documents submitted: 9
- documents indexed: 9
- chunks indexed: 9
- skipped documents: 0
- write posture: `suggestion_only`
- direct WordPress write: false

Successful search:

- run: `run_318cd6d61b4642fd93549911c1945774`
- intent: `writing_support_plan`
- evidence gate: passed
- result count: 5
- provider: `site_knowledge`
- model: `site-knowledge-managed`
- direct WordPress write: false

Successful status:

- run: `run_0c36b9da127a487889a6ecbe41698067`
- index status: ready
- quota status: ok
- document utilization: `0.0009`

## WordPress Content State

Current read-only WordPress counts remain consistent with prior phases:

- public `post` / `page`: `1968`
- public `post`: `1967`
- public `page`: `1`

This supports the claim that the trial did not mutate WordPress content.

## Decision

GO:

- Treat the `npcink-trial` clone as valid staging proof for:
  - dedicated Cloud site identity;
  - verified WordPress addon connection;
  - hosted runtime execution;
  - usage, credit, billing, and run evidence;
  - bounded public Site Knowledge sync/search/status;
  - fail-closed data guard behavior;
  - suggestion-only handoff back to WordPress-local approval.
- Proceed to a larger `npcink-trial` staging batch.

NO-GO:

- Do not run this against `npcink.local`, `dbd.local`, `wp.local`, or any live
  site without second explicit approval naming the exact site.
- Do not sync the full live corpus yet.
- Do not invite customer use yet.
- Do not enable direct publish, direct write, article body generation, batch
  generation, self-serve onboarding, or payment-facing behavior.
- Do not reuse this trial as proof that full-corpus or live-site PII posture is
  already solved.

## Required Before Live

Before any live-site execution, require:

1. second explicit approval naming the exact live site;
2. fresh live-site backup and rollback path;
3. live content category review and PII sampling;
4. a decision on dedicated live Cloud identity versus trial identity;
5. redacted addon option snapshot;
6. documented rollback for the addon option;
7. operator watching run logs, usage, credit, and billing detail;
8. a smaller live dry run before any larger live index;
9. no direct WordPress writes unless a separate WordPress-local approval path is
   explicitly exercised.

## Next Safe Action

Recommended next phase: larger `npcink-trial` staging batch, still with no
WordPress writes.

Suggested constraints:

- 50 to 100 public `post` / `page` documents;
- public data only;
- no comments, users, drafts, private posts, credentials, or raw admin data;
- keep output `suggestion_only`;
- keep `direct_wordpress_write=false`;
- record run, usage, credit, billing, data guard, and search evidence;
- stop and close out before considering live execution.

Alternative safe action: prepare a live-site preflight only. That preflight must
remain read-only and cannot execute runtime or Site Knowledge until separately
approved.
