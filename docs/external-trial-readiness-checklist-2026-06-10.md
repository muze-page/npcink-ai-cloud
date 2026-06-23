# External Trial Readiness Checklist - 2026-06-10

Status: active checklist.

Scope: first controlled external trial of Npcink AI Cloud hosted runtime and
reviewable WordPress assistance.

Source note:

- Capability boundary:
  `docs/external-trial-capability-note-2026-06-10.md`
- Content boundary:
  `docs/cloud-content-generation-boundary-v1.md`
- Bulk article prohibition:
  `docs/cloud-bulk-article-run-v1.md`
- Agent feedback boundary:
  `docs/cloud-agent-feedback-contract-v1.md`

This checklist is for controlled trial readiness, not GA readiness. It does not
approve payment front-office work, unrestricted self-serve onboarding, Cloud
content generation as a product, or any Cloud-side WordPress write authority.

## Trial Definition

The external trial is ready when a small number of approved sites can use the
normal WordPress/Toolbox path to call Cloud hosted runtime features, receive
reviewable results, submit structured feedback, and leave enough operational
evidence for support without moving approval or write truth into Cloud.

Trial posture:

`approved sites only -> hosted runtime assistance -> local review/write owner -> Cloud eval/support evidence`

## P0 Gate - Must Pass Before Inviting Sites

| Gate | Required state | Evidence |
| --- | --- | --- |
| Boundary | Cloud remains runtime/detail/eval only | This checklist plus capability note reviewed |
| Smoke baseline | Hosted runtime, onboarding, and Site Knowledge smoke pass | `pnpm run smoke:internal-alpha-onboarding`; `pnpm run smoke:local-alpha`; `pnpm run smoke:site-knowledge` |
| Test baseline | Contract/domain/API/perimeter lanes pass | `pnpm run check:fast`; `pnpm run check:seam` |
| Toolbox baseline | Toolbox suggestion and Core handoff tests pass | Toolbox `composer test:all`; `composer smoke:site-knowledge-review-ui` |
| Operational readiness | Target environment reports ready | `/health/operational-ready` returns ready |
| Site eligibility | Trial site is approved before key issuance | Manual site record and declared use case |
| Cloud API key | Key is provisioned, active, saved, and verified in addon | WordPress Cloud addon verified state |
| Provider readiness | Required hosted providers are configured and fresh | Provider health summary fresh |
| Abuse boundary | High-risk categories are denied or require manual review | Trial intake record |
| WordPress write boundary | Final writes stay local/Core | No Cloud write endpoint or direct publishing path used |
| AI disclosure | Trial operator knows outputs may need AI labels | Disclosure note provided to operator |
| Support evidence | Run, usage, error, provider, and feedback evidence are inspectable | Cloud diagnostics and feedback summary |
| Rollback | Operator can revoke key or suspend site | Service-plane action path confirmed |

Do not invite external sites until every P0 row is satisfied for the target
environment.

## P0 Execution Steps

1. Select trial site
   - Confirm site URL, owner/contact, declared use case, and content category.
   - Reject or hold for manual review if the site is primarily sexual content,
     gambling, fraud, phishing, fake reviews, spam/doorway pages, copyright
     laundering, or regulated high-stakes advice without a separate approval.

2. Provision Cloud access
   - Provision the site through existing service-plane/dev seed path.
   - Issue or confirm an active Cloud API key.
   - Save and verify the key in `npcink-cloud-addon`.
   - Do not expose split `site_id / key_id / secret` fields in WordPress UI.

3. Confirm environment readiness
   - Start the API, runtime worker, callback worker, ops worker, Redis,
     Postgres, frontend, and proxy through the existing Docker Compose stack.
   - Confirm `/health/operational-ready` is ready.
   - Confirm provider health and cadence freshness are current.

4. Run Cloud verification
   - From `/Users/muze/gitee/npcink-ai-cloud`:

```bash
pnpm run check:fast
pnpm run check:seam
pnpm run smoke:internal-alpha-onboarding
pnpm run smoke:site-knowledge
pnpm run smoke:local-alpha
```

5. Run Toolbox verification
   - From `/Users/muze/gitee/npcink-toolbox`:

```bash
composer test:all
composer smoke:site-knowledge-review-ui
```

6. Capture evidence
   - Record smoke evidence JSON paths.
   - Record target Cloud base URL and WordPress site URL.
   - Record run IDs for hosted runtime and Site Knowledge smoke.
   - Record whether any test was skipped and why.

7. Trial operator briefing
   - State that outputs are suggestions, candidates, analysis, or
     `proposal_input`.
   - State that Cloud does not publish content.
   - State that article bodies, bulk article drafts, fake reviews, gambling
     promotion, sexual content generation, phishing, scams, spam, and
     copyright-laundering use cases are out of scope.
   - State that local/Core remains the approval and write owner.

8. Go/no-go decision
   - Invite the site only if P0 evidence is complete.
   - If any P0 item fails, record the failure under `Trial Blockers` and do not
     compensate by adding a new Cloud control surface.

## Trial Blockers

Any of these blocks the trial for a site or environment:

- `/health/operational-ready` is not ready.
- Hosted runtime smoke fails without a clear environment-only cause.
- Site Knowledge smoke fails or returns ungrounded/no-evidence output.
- Agent feedback receipt indicates production mutation or Cloud approval truth.
- Cloud returns article body, SEO copy, bulk article plan, or
  `article_write_plan` for `writing_support_plan`.
- WordPress content is mutated directly by Cloud assistance.
- The site category matches a prohibited or manual-review category.
- Provider keys, split credentials, or secrets are exposed in WordPress UI or
  customer-facing logs.
- Support cannot inspect run/error/usage evidence.
- Operator cannot revoke key or suspend the site.

## P1 - Recommended For First Trial Batch

These are not required to start a controlled trial, but should be done before
expanding beyond the first few sites:

- Prepare a short operator runbook with:
  - invite criteria
  - key issuance steps
  - smoke commands
  - revocation/suspension steps
  - support evidence paths
  - Current artifact:
    `docs/external-trial-operator-runbook-2026-06-11.md`
- Prepare trial copy that uses:
  - "reviewable suggestions"
  - "writing preparation"
  - "hosted runtime assistance"
  - "Cloud-managed evidence"
  - Current artifact:
    `docs/external-trial-copy-and-log-2026-06-11.md`
- Remove or revise any copy that implies:
  - automatic article generation
  - direct publishing
  - unrestricted content automation
  - fake engagement generation
- Create a simple trial log with:
  - site ID
  - use case
  - invite date
  - smoke evidence
  - blocked prompts or abuse signals
  - operator notes
  - feedback summary
  - Current artifact:
    `docs/external-trial-copy-and-log-2026-06-11.md`
- Review first-trial feedback weekly before changing prompts, profiles,
  routing, or UX.

## P2 - Explicitly Deferred

Do not treat these as blockers for the first controlled trial:

- self-serve customer onboarding
- payment, invoice, dunning, or seat lifecycle
- public marketplace or model marketplace
- Cloud prompt editor, router editor, or workflow builder
- Cloud ability registry or MCP platform
- generic Agent Gateway
- second scheduler, workflow engine, or heavy orchestration stack
- broader commercial portal polish
- bulk content automation

These require a separate boundary review before implementation.

## Evidence Record Template

Use this block for each trial target:

```markdown
## Trial Target

- Date:
- Environment:
- Cloud base URL:
- WordPress site URL:
- Site ID:
- Declared use case:
- Site category review:
- Cloud API key verified: yes/no
- Provider health fresh: yes/no
- Operational ready: yes/no

## Verification

- `pnpm run check:fast`:
- `pnpm run check:seam`:
- `pnpm run smoke:site-knowledge`:
- Site Knowledge evidence JSON:
- `pnpm run smoke:local-alpha`:
- Local alpha evidence JSON:
- Toolbox `composer test:all`:
- Toolbox `composer smoke:site-knowledge-review-ui`:

## Boundary Confirmation

- Cloud article generation absent:
- Bulk article generation absent:
- `writing_support_plan` returns pre-draft assistance only:
- Agent feedback production mutation false:
- WordPress final write owner remains local/Core:
- Prohibited use categories reviewed:

## Decision

- Go/no-go:
- Blockers:
- Operator notes:
```

## Maintainer Rule

When updating this checklist, keep changes in one of these buckets:

- trial eligibility
- verification evidence
- abuse/legal boundary
- support/rollback evidence
- local/Core write-boundary confirmation

Do not add new Cloud product surfaces, approval paths, write paths, registries,
or infrastructure from this checklist. If a checklist item appears to require
one of those, write a separate boundary proposal first.
