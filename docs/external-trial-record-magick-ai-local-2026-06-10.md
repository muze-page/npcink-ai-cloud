# External Trial Record - npcink.local - 2026-06-10

Status: local dry-run complete; not an external customer invite.

Purpose: exercise the external trial readiness checklist against the current
local WordPress and Cloud environment before inviting any external site.

Read first:

- `docs/external-trial-capability-note-2026-06-10.md`
- `docs/external-trial-readiness-checklist-2026-06-10.md`
- `docs/cloud-content-generation-boundary-v1.md`
- `docs/cloud-bulk-article-run-v1.md`
- `docs/cloud-agent-feedback-contract-v1.md`

## Trial Target

- Date: 2026-06-10
- Environment: local alpha dry-run
- Cloud base URL: `http://127.0.0.1:8010`
- WordPress site URL: `https://npcink.local/`
- Site ID: `site_npcink_local`
- Declared use case: verify hosted runtime assistance, Site Knowledge evidence,
  writing preparation, and Agent feedback boundaries before external trial.
- Site category review: low-risk local development site; not a sexual,
  gambling, phishing, fake-review, spam, copyright-laundering, or regulated
  high-stakes advice site.
- Cloud API key verified: yes, WordPress Cloud addon page showed verified state
  during `pnpm run smoke:local-alpha`.
- Provider health fresh: yes, operational readiness passed during
  `pnpm run smoke:local-alpha`.
- Operational ready: yes, `pnpm run smoke:local-alpha` passed after starting
  API, runtime worker, callback worker, ops worker, frontend, proxy, Redis, and
  Postgres.

## Verification

- `pnpm run check:fast`: passed before this dry-run record.
  - Contract: 40 passed, 2 skipped.
  - Domain: 89 passed, 3 skipped.
- `pnpm run check:seam`: passed before this dry-run record.
  - API: 307 passed.
  - Perimeter: 9 passed.
- `pnpm run smoke:site-knowledge`: passed.
- Site Knowledge evidence JSON:
  `/Users/muze/gitee/npcink-cloud/.tmp/site-knowledge-real-chain-smoke/evidence-20260610085114.json`
- Site Knowledge sync run ID: `run_d97fa56b2ffb44b3b91deccd982ad383`
- Site Knowledge evidence gate: passed.
- `pnpm run smoke:local-alpha`: passed.
- Local alpha evidence JSON:
  `/Users/muze/gitee/npcink-cloud/.tmp/local-alpha-smoke/evidence-20260610090134.json`
- Hosted runtime run ID: `run_7fd3bf61107d47cd8df58c9b3876e5a7`
- Hosted runtime status: succeeded.
- Hosted runtime provider ID: `openai`
- Hosted runtime model ID: `ByteDance-Seed/Seed-OSS-36B-Instruct`
- Toolbox `composer test:all`: passed before this dry-run record.
- Toolbox `composer smoke:site-knowledge-review-ui`: passed before this
  dry-run record.

## Boundary Confirmation

- Cloud article generation absent: confirmed by existing contract tests and
  `docs/cloud-bulk-article-run-v1.md`.
- Bulk article generation absent: confirmed by `pnpm run test:contract` in the
  `check:fast` lane.
- `writing_support_plan` returns pre-draft assistance only: confirmed by
  focused Cloud API test before this record; the feature must not return
  article bodies, SEO copy, or Cloud-produced `article_write_plan` candidates.
- Agent feedback production mutation false: confirmed by focused Cloud Agent
  feedback route tests before this record.
- WordPress final write owner remains local/Core: confirmed by Toolbox
  suggestion/Core handoff tests and Site Knowledge review UI smoke.
- Prohibited use categories reviewed: local dry-run target is not in a blocked
  category.

## Decision

- Go/no-go: go for local dry-run only.
- External invite decision: hold until a real external low-risk site is selected
  and this same record template is filled for that site.
- Blockers: none for local dry-run.
- Operator notes:
  - Do not expand trial beyond `writing_support_plan`, Site Knowledge
    evidence/search, hosted runtime assistance, and Agent feedback eval until a
    real low-risk site passes this same checklist.
  - Do not market this as article generation, bulk content automation, or
    direct publishing.
  - If a real trial site is selected, create a separate record file rather than
    editing this dry-run record.

## Allowed First Trial Surfaces

For the first external site, expose only:

- Site Knowledge evidence/search.
- `writing_support_plan` writing preparation.
- Hosted runtime assistance through the normal Toolbox/Cloud path.
- Agent feedback submission and read-only summary for evaluation.

Do not expose:

- Cloud article generation.
- Bulk article generation.
- Cloud-generated `article_write_plan` candidates.
- Direct WordPress publishing.
- Cloud prompt/router/workflow editing.
- Fake review, gambling, adult, phishing, spam, or copyright-laundering
  generation.
