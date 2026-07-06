# External Trial Record - npcink.local - 2026-06-15

Status: local rehearsal complete; not an external customer invite.

Purpose: re-run the first-site evidence path against the current local
WordPress and Cloud baseline before selecting a real external low-risk trial
site.

This record is intentionally local-only. It must not be counted as the first
real external site.

Historical ID note: this document records the old Free package ID
`plan_free_v1`; current package records use `free` / `free_v1`.

Read first:

- `docs/external-trial-handoff-summary-2026-06-15.md`
- `docs/external-trial-capability-note-2026-06-10.md`
- `docs/external-trial-readiness-checklist-2026-06-10.md`
- `docs/external-trial-operator-runbook-2026-06-11.md`
- `docs/external-trial-copy-and-log-2026-06-11.md`
- `docs/cloud-content-generation-boundary-v1.md`
- `docs/cloud-bulk-article-run-v1.md`
- `docs/cloud-agent-feedback-contract-v1.md`
- `docs/ai-credit-ledger-detail-summary-2026-06-13.md`

## Trial Target

- Date: 2026-06-15
- Environment: local alpha rehearsal
- Cloud commit SHA: `245f2c4`
- Cloud base URL: `http://127.0.0.1:8010`
- WordPress site URL: `https://npcink.local/`
- WordPress admin username: `1`
- WordPress admin password: `[REDACTED_SECRET]`
- Site ID: `site_npcink_local`
- Declared use case: verify the hosted runtime assistance, Site Knowledge
  evidence, writing preparation, Agent feedback boundary, and usage /
  entitlement / billing detail evidence before any real external site invite.
- Site category review: low-risk local development site; not a sexual,
  gambling, phishing, fake-review, spam, copyright-laundering, or regulated
  high-stakes advice site.
- Cloud API key verified: yes; WordPress Cloud addon admin page was reachable
  and the smoke path verified the addon settings route.
- Provider health fresh: yes; provider observability reported `fresh` with
  98 healthy instances across 2 providers.
- Operational ready: yes; `/health/operational-ready` reported `ok=true` with
  required runtime, callback, and ops workers present.

## Verification

- `pnpm run check:fast`: passed after updating the commercial runtime default
  test for the current AI credit budget field.
  - Contract: 41 passed, 2 skipped.
  - Domain: 94 passed, 3 skipped.
- `pnpm run check:seam`: passed.
  - API: 320 passed.
  - Perimeter: 9 passed.
- `pnpm run smoke:internal-alpha-onboarding`: passed, 1 test.
- `pnpm run smoke:site-knowledge`: passed.
- Site Knowledge evidence JSON:
  `/Users/muze/gitee/npcink-cloud/.tmp/site-knowledge-real-chain-smoke/evidence-20260615050032.json`
- Site Knowledge sync run ID: `run_1c8ac355e28a4d3e913c1479681b3f5e`
- Site Knowledge evidence gate: passed.
- `pnpm run smoke:local-alpha`: passed after updating the smoke script to the
  current Portal CLI/session contract.
- Local alpha evidence JSON:
  `/Users/muze/gitee/npcink-cloud/.tmp/local-alpha-smoke/evidence-20260615050537.json`
- Hosted runtime run ID: `run_5a42bd6453bc4c01a328b9e90b0c3570`
- Hosted runtime status: succeeded.
- Hosted runtime provider ID: `openai`
- Hosted runtime model ID: `codex-auto-review`
- Hosted runtime fallback used: yes; initial ByteDance Seed provider call timed
  out and routed to the fallback OpenAI instance.
- OpenClaw read-only analysis run ID:
  `run_2c72ae5f754347329a016ffe8c9b06e6`
- Toolbox `composer test:all`: not run in this Cloud rehearsal pass
- Toolbox `composer smoke:site-knowledge-review-ui`: not run in this Cloud
  rehearsal pass

## Runtime And Detail Evidence

- Request ID: not emitted in the local alpha evidence JSON; run IDs above are
  the primary correlation handles for this rehearsal.
- Run ID: `run_5a42bd6453bc4c01a328b9e90b0c3570`
- Provider health: fresh; 98 healthy instances, 0 degraded, 0 unhealthy.
- Route selected: `openai-global-codex-auto-review`
- API key verified: yes; `key_npcink_local` was active and had a
  `last_used_at` timestamp of `2026-06-15T05:07:05.165736+00:00`.
- Usage meter entry: present; current smoke period totals were 2 runs, 4
  provider calls, 615 input tokens, 434 output tokens, and 1049 total tokens.
- Usage ledger entry: present; credit ledger returned 8 current-period entries
  for `acct_site_npcink_local`.
- AI credit consumption: 4 recorded credits total under
  `ai-credit-ledger-v2`, split as 2 hosted-run credits, 2 model-token credits,
  and 0 other-provider-call credits.
- Entitlement snapshot: present; `plan_free_v1` budgets were normalized with
  `max_ai_credits_per_period`, `max_runs_per_period`,
  `max_tokens_per_period`, and `max_cost_per_period` all at `0.0`, meaning no
  package-limit block in the local development baseline.
- Billing/detail snapshot: present;
  `bill_site_npcink_local_sub_site_npcink_local_1781499941_1784091941`
  reconciled the same 2 runs, 4 provider calls, and 1049 total tokens.
- Audit event: recent service audit records exist for the local site, but the
  latest listed events were older runtime repair/internal advisor records, not
  a new customer-facing write event from this rehearsal.
- Callback worker result: healthy; callback queue had 0 pending, 0 failed, and
  `pressure_state=healthy`.
- Guard events: historical stale timestamp rejections exist for
  `site_npcink_local`; no new guard pressure appeared in the local alpha
  evidence, and runtime queue pressure remained healthy.

## Boundary Confirmation

- Cloud article generation absent: confirmed by contract lane and rehearsal
  scope; this run did not expose Cloud article body generation.
- Bulk article generation absent: confirmed by contract lane and rehearsal
  scope.
- `writing_support_plan` returns pre-draft assistance only: not directly rerun
  in this pass; remains covered by the active capability boundary and prior
  contract/readiness docs.
- Agent feedback production mutation false: not directly rerun in this pass;
  rehearsal did not expose mutation paths.
- WordPress final write owner remains local/Core: confirmed by scope and
  observed behavior; the smoke used read/review/runtime paths only and did not
  perform direct Cloud publishing.
- Prohibited use categories reviewed: yes, local rehearsal target is not in a
  blocked category.

## Decision

- Go/no-go: go for local rehearsal only.
- External invite decision: hold; this is a local rehearsal only.
- Blockers: none remaining for local rehearsal.
- Operator notes:
  - Do not count this record as the first real external trial site.
  - Initial run exposed two contract-drift fixes:
    - `tests/domain/test_commercial_runtime_defaults.py` needed to include
      `max_ai_credits_per_period` in the normalized dev budget expectation.
    - `scripts/local-alpha-smoke.sh` needed to call
      `bootstrap_portal_site.py --site-admin-email` and read
      `data.site_admin_ref` from the Portal session response.
  - Do not expose Cloud article generation, bulk drafts, direct publishing,
    Cloud prompt/router/workflow editing, Cloud ability registry, or MCP
    platform behavior.
  - Treat failures as environment, boundary, evidence, runbook, or runtime
    blockers before considering any new feature work.

## Allowed Rehearsal Surfaces

Expose only:

- Site Knowledge evidence/search.
- `writing_support_plan` writing preparation.
- Hosted runtime assistance through the normal Toolbox/Cloud path.
- Agent feedback submission and read-only summary for evaluation.
- Usage, entitlement, billing/detail, audit, callback, and guard evidence
  needed to explain the hosted runtime activity.

Do not expose:

- Cloud article generation.
- Bulk article generation.
- Cloud-generated `article_write_plan` candidates.
- Direct WordPress publishing.
- Cloud prompt/router/workflow editing.
- Cloud skill registry, MCP platform, or Agent Gateway platform behavior.
- Fake review, gambling, adult, phishing, spam, or copyright-laundering
  generation.
