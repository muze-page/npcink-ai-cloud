# External Trial Handoff Summary - 2026-06-15

Status: active handoff summary.

Purpose: summarize the recent Cloud positioning, content-risk boundary,
external-trial preparation work, and next required action so another engineer or
AI agent can continue without rereading the whole conversation.

This document is an engineering and product handoff. It is not legal advice.
Counsel should review jurisdiction-specific terms before GA or broader
commercial release.

## One-Line Positioning

Magick AI Cloud is the hosted runtime and service-detail layer for the local
Magick AI WordPress stack.

It is not:

- a second WordPress control plane
- a second ability or workflow registry
- a prompt/router/preset truth source
- a cloud article factory
- a direct publishing system
- an unrestricted content-generation API

The safe product sentence is:

`hosted AI runtime for reviewable WordPress assistance, not a cloud content factory`

## Repository Roles

- `magick-ai-abilities`: ability definitions, schemas, callbacks, and
  permission metadata.
- `magick-ai-core`: governance, proposal review, approval, preflight, and
  audit.
- `magick-ai-adapter`: OpenClaw channel adapter that calls Core and WordPress
  Abilities API.
- `magick-ai-cloud-addon`: thin WordPress connector for Cloud URL/API key,
  signing, hosted runtime calls, and read-only service status.
- `magick-ai-cloud`: hosted runtime, provider routing/execution, usage,
  entitlement, health, diagnostics, service-plane evidence, Site Knowledge, and
  Agent feedback evaluation data.

## Content And Legal-Risk Conclusion

The chosen posture is not "ban every content-related AI feature."

The chosen posture is:

- allow reviewable assistance
- prohibit Cloud article-generation product surfaces
- keep local/Core as final approval and write owner
- deny or manually review high-risk site categories and prompt classes
- preserve audit, evidence, revocation, and suspension paths

Allowed first-trial content-adjacent capabilities:

- Site Knowledge evidence/search
- `writing_support_plan`
- hosted runtime assistance through the normal Toolbox/Cloud path
- Agent feedback eval
- image-source or AI image candidates only as reviewable candidates
- metadata, summary, category, tag, link, or media suggestions when local review
  remains the adoption path

Explicitly prohibited or out of trial scope:

- Cloud article body generation
- batch article drafts
- Cloud-produced `article_write_plan` candidates
- direct WordPress publishing
- fake reviews, fake comments, or fake testimonials
- gambling, adult, phishing, scam, spam, doorway-page, or low-quality SEO site
  farm use cases
- copyright laundering or unauthorized rewriting
- regulated high-stakes advice without separate approval
- any feature that moves approval, ability truth, workflow truth, prompt truth,
  router truth, or WordPress writes into Cloud

## Boundary Checks Applied

The work followed the Cloud boundary rule:

- local plugin/Core remains the control plane
- Cloud remains runtime/detail/eval only
- Redis/queue/callback are not canonical truth
- final WordPress writes stay local/Core
- no Temporal/Celery/Kafka/RabbitMQ/NATS/Kubernetes-first expansion
- no Cloud skill registry, MCP platform, Agent Gateway, prompt editor, router
  editor, workflow builder, or direct write owner

## Work Already Completed

### Smoke and test stabilization

Committed and pushed:

- `f9313cb Stabilize hosted runtime smoke checks`

Main effects:

- fixed test secret isolation for HMAC contract tests
- fixed Site Knowledge smoke polling when `/runs/{id}/result` returns
  `200 + running progress`
- made `smoke:local-alpha` start and restart the required dev workers:
  `worker`, `callback-worker`, and `ops-worker`
- updated README hosted runtime smoke command to `pnpm run smoke:local-alpha`

### Trial capability boundary

Committed and pushed:

- `615d00b Document external trial capability boundary`

Main file:

- `docs/external-trial-capability-note-2026-06-10.md`

Purpose:

- defines trial-ready capabilities
- records explicit non-promises
- records content/legal-risk boundary
- records Agent feedback as eval metadata only
- lists minimal external-trial acceptance checks

### Trial readiness checklist

Committed and pushed:

- `1626e15 Add external trial readiness checklist`

Main file:

- `docs/external-trial-readiness-checklist-2026-06-10.md`

Purpose:

- P0 gates before inviting sites
- P0 execution steps
- trial blockers
- P1 recommendations
- P2 deferred items
- evidence record template

### Local dry-run record and user briefing

Committed and pushed:

- `e9aa6a8 Add first trial dry-run record and briefing copy`

Main files:

- `docs/external-trial-record-magick-ai-local-2026-06-10.md`
- `docs/external-trial-user-briefing-copy-zh-2026-06-10.md`

Purpose:

- records `https://magick-ai.local/` as a local dry-run only
- confirms this is not an external customer invite
- provides Chinese trial briefing copy that avoids article-generation and
  direct-publishing claims

### Later controlled-trial support docs now present

Current repo also contains:

- `docs/external-trial-operator-runbook-2026-06-11.md`
- `docs/external-trial-copy-and-log-2026-06-11.md`

These are the current short runbook and copy/log template for first approved
trial sites. Prefer these for the operational execution path, while using the
June 10 files as the boundary and readiness rationale.

### AI credit ledger detail

Committed and pushed:

- `ffbb239 Add AI credit ledger detail views`
- `79502d9 Document AI credit ledger details`

Main file:

- `docs/ai-credit-ledger-detail-summary-2026-06-13.md`

Purpose:

- moves current-period consumption detail from estimate-first presentation to
  ledger-backed admin and Portal views
- adds current-period credit ledger read surfaces for admin account detail and
  Portal usage detail
- keeps AI credit consumption as integer units under the current
  `ai-credit-ledger-v2` rate version
- keeps this work inside the usage, entitlement, and billing detail boundary

Boundary:

- this is not a wallet, permanent credit balance, payment checkout, invoice
  front office, dunning surface, customer self-serve top-up, or second
  WordPress control plane
- first real-site trial evidence should confirm that usage ledger, entitlement,
  and billing/detail snapshots can explain the same hosted runtime activity

## Verification Already Run

Cloud:

```bash
pnpm run check:fast
pnpm run check:seam
pnpm run smoke:site-knowledge
pnpm run smoke:local-alpha
```

Observed results during the stabilization pass:

- `check:fast`: contract and domain passed.
- `check:seam`: API `307 passed`; perimeter `9 passed`.
- `smoke:site-knowledge`: passed.
- `smoke:local-alpha`: passed.

Toolbox:

```bash
composer test:all
composer smoke:site-knowledge-review-ui
```

Observed result:

- both passed during the trial-boundary work.

Evidence JSON paths recorded:

- `/Users/muze/gitee/magick-ai-cloud/.tmp/site-knowledge-real-chain-smoke/evidence-20260610085114.json`
- `/Users/muze/gitee/magick-ai-cloud/.tmp/local-alpha-smoke/evidence-20260610090134.json`

Key local dry-run evidence:

- Cloud base URL: `http://127.0.0.1:8010`
- WordPress URL: `https://magick-ai.local/`
- Site ID: `site_magick_ai_local`
- Site Knowledge sync run ID: `run_d97fa56b2ffb44b3b91deccd982ad383`
- Hosted runtime run ID: `run_7fd3bf61107d47cd8df58c9b3876e5a7`
- Hosted runtime status: `succeeded`

## Current Git State At Handoff

Before this summary file was added, the repo was clean and synced:

```text
## master...origin/master
```

Latest relevant pushed commits:

```text
79502d9 Document AI credit ledger details
ffbb239 Add AI credit ledger detail views
e9aa6a8 Add first trial dry-run record and briefing copy
1626e15 Add external trial readiness checklist
615d00b Document external trial capability boundary
f9313cb Stabilize hosted runtime smoke checks
```

Current HEAD at this handoff baseline:

```text
79502d9 Document AI credit ledger details
```

## What To Do Next

Do not add new features yet.

Next action is to select one real low-risk external trial site and create a
real go/no-go record.

Required site information:

- site URL
- site owner/contact
- site type or industry
- declared use case
- site category review
- target Cloud base URL
- whether `magick-ai-cloud-addon` is installed and verified
- whether the operator accepts the briefing copy
- whether the trial will expose only:
  - Site Knowledge evidence/search
  - `writing_support_plan`
  - hosted runtime assistance
  - Agent feedback eval

Suggested real-record filename:

```text
docs/external-trial-record-<site-slug>-2026-06-15.md
```

Use the template in:

- `docs/external-trial-copy-and-log-2026-06-11.md`
- or `docs/external-trial-readiness-checklist-2026-06-10.md`

## Go/No-Go Rule For First Real Site

Go only if:

- site category is low-risk or explicitly approved
- Cloud API key is active and verified in the addon
- `/health/operational-ready` is ready in the target environment
- Cloud smoke checks pass
- Toolbox checks pass or have a documented environment-only reason
- evidence JSON paths and run IDs are recorded
- usage ledger, entitlement, and billing/detail evidence explain the same
  runtime activity
- operator has received the briefing copy
- final write owner remains local WordPress/Core

No-go if:

- the site is primarily adult, gambling, phishing, scam, fake-review, spam,
  doorway-page, copyright-laundering, or unapproved high-stakes advice
- the operator expects automatic article generation, direct publishing, or
  unrestricted content automation
- smoke evidence is missing
- support cannot inspect run/error/usage evidence
- usage ledger and billing/detail snapshots cannot be reconciled for the trial
  run
- revocation or suspension path is unclear
- any step requires Cloud to become a second control plane

## Handoff To Another AI

When another AI continues this work, instruct it to:

1. Read this file first.
2. Then read:
   - `docs/external-trial-operator-runbook-2026-06-11.md`
   - `docs/external-trial-copy-and-log-2026-06-11.md`
   - `docs/external-trial-capability-note-2026-06-10.md`
   - `docs/external-trial-readiness-checklist-2026-06-10.md`
3. Ask for the first real site details if they are not provided.
4. Create one site-specific trial record.
5. Run or record the relevant evidence.
6. Do not broaden product scope during the first real trial.

## Boundary-Safe Summary

The work is at a clean handoff point.

The current objective is not more Cloud features. The current objective is a
single real low-risk trial site with a completed go/no-go record.

Only after one real site passes should the trial expand to three sites.
