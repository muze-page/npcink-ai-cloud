# External Trial Capability Note - 2026-06-10

Status: active trial handoff.

Purpose: give future engineers and AI agents a single, repo-grounded summary of
what Npcink AI Cloud can expose for trial use now, what must stay prohibited,
and how to verify the current hosted runtime loop without turning Cloud into a
content factory or a second WordPress control plane.

This is a product and engineering boundary note, not legal advice. Legal
language must be reviewed by counsel before GA.

## Current Product Position

Npcink AI Cloud is a hosted runtime and service-detail layer for the local
Magick AI stack.

Current trial positioning:

`hosted AI runtime for reviewable WordPress assistance, not a cloud content factory`

Cloud may execute bounded AI tasks, collect runtime evidence, and aggregate
structured feedback for evaluation. Cloud must not own WordPress approval,
publishing, ability truth, workflow truth, prompt truth, router truth, or final
write execution.

## Repository Split

- `magick-ai-abilities`: ability definitions, schemas, callbacks, and
  permission metadata.
- `magick-ai-core`: governance, proposal review, approval, preflight, and
  audit.
- `magick-ai-adapter`: OpenClaw channel adapter that calls Core and the
  WordPress Abilities API.
- `npcink-cloud-addon`: thin WordPress connector for Cloud URL/API key,
  signing, hosted runtime calls, and read-only service status.
- `npcink-ai-cloud`: hosted runtime, routing, provider execution, usage,
  entitlement, health, diagnostics, service-plane audit evidence, Site
  Knowledge, and structured Agent feedback evaluation data.

## Trial-Ready Capabilities

These capabilities are trial-ready when the site is provisioned, the Cloud API
key is verified, and local WordPress/Core remains the write owner:

- hosted text runtime through the normal runtime and Toolbox path
- Site Knowledge sync, search, and evidence-backed writing preparation
- `writing_support_plan` outputs that return pre-draft tasks and evidence
- Web Search as Cloud-managed external evidence
- image-source and AI image candidate generation as reviewable candidates
- Agent feedback submission and summary as evaluation metadata
- operational readiness, runtime diagnostics, usage, provider health, and audit
  detail for support

## Explicit Non-Promises

Do not describe the trial as any of these:

- automatic article writer
- bulk article generator
- cloud publishing platform
- WordPress autopilot
- prompt or router control plane
- AI SEO site-farm tool
- fake review or comment generator
- gambling, adult, phishing, scam, or spam content tool

## Content And Legal Risk Boundary

The current posture is not "ban every content-related AI feature." The safer
rule is narrower:

- allow reviewable assistance, summaries, outlines, metadata suggestions,
  writing preparation, evidence packs, and candidate artifacts
- prohibit Cloud article writing generation, batch article drafts, long-form
  article bodies, Cloud-produced `article_write_plan` candidates, direct
  publishing, and unrestricted automation
- deny, suspend, revoke key, or require manual review for high-risk categories
  such as sexual content generation, gambling promotion, fraud, phishing, fake
  reviews, spam, copyright laundering, and regulated high-stakes advice without
  a separate approved product review

Required customer-facing posture:

- every output is a draft, suggestion, candidate, analysis result, or
  `proposal_input`
- final WordPress writes go through local Core approval, preflight, and audit
- AI labeling and disclosure follow `docs/ai-generated-content-disclosure-v1.md`
- content-generation boundaries follow
  `docs/cloud-content-generation-boundary-v1.md`
- bulk article prohibition follows `docs/cloud-bulk-article-run-v1.md`

## Agent Feedback Boundary

Agent feedback is trial-ready only as evaluation metadata.

Allowed:

- local review outcome submission
- fixed eval labels
- Cloud summary and quality rollup
- evidence for future recommendation improvement

Forbidden:

- Cloud-side approval truth
- Cloud-side production mutation
- automatic prompt, preset, router, profile, entitlement, billing, content, or
  WordPress write changes from feedback events

See `docs/cloud-agent-feedback-contract-v1.md` and
`docs/cloud-agent-positioning-v1.md`.

## Current Verification Evidence

The current local alpha verification evidence is:

- `/Users/muze/gitee/npcink-cloud/.tmp/local-alpha-smoke/evidence-20260611050446.json`
- `/Users/muze/gitee/npcink-cloud/.tmp/site-knowledge-real-chain-smoke/evidence-20260611050150.json`

Commands used for the verified baseline:

```bash
pnpm run check:fast
pnpm run check:seam
pnpm run smoke:site-knowledge
pnpm run smoke:local-alpha
```

Additional Toolbox-side verification:

```bash
composer test:all
composer smoke:site-knowledge-review-ui
```

First-batch operator assets:

- `docs/external-trial-operator-runbook-2026-06-11.md`
- `docs/external-trial-copy-and-log-2026-06-11.md`

## Minimal External Trial Acceptance Table

| Area | Acceptance check | Required result | Evidence command |
| --- | --- | --- | --- |
| Hosted runtime | User path can trigger hosted text runtime through normal Cloud/Toolbox path | Run succeeds with result or readable layer-specific error | `pnpm run smoke:local-alpha` |
| Operational readiness | API, runtime worker, callback worker, ops cadence, provider health, and cadence tasks are fresh | `/health/operational-ready` returns ready in the target environment | `pnpm run smoke:local-alpha` |
| Site Knowledge | Isolated site can sync, search, and return grounded evidence | Sync completes, search returns evidence-backed results, no WordPress write | `pnpm run smoke:site-knowledge` |
| Writing support | Cloud returns preparation tasks, not article bodies or SEO copy | `writing_support_plan` returns pre-draft assistance and blocked output fields stay blocked | focused Cloud API/domain tests |
| Bulk article boundary | Cloud does not expose bulk article generation or Cloud article-writing runs | Contract tests reject or prove absence of prohibited surfaces | `pnpm run test:contract` |
| Agent feedback | Feedback enters eval rollup only | Receipt marks production mutation false and local approval truth intact | focused agent feedback tests |
| API seam | Public/runtime/internal API contracts stay stable | API suite passes | `pnpm run check:seam` |
| Perimeter | Removed or forbidden surfaces stay absent | Perimeter suite passes | `pnpm run check:seam` |
| WordPress boundary | Toolbox surfaces remain suggestion-only or Core handoff | No direct WordPress content mutation from Cloud assistance | Toolbox `composer test:all` and smoke checks |

## Next Implementation Rule

Before adding any new content or Agent feature, answer these questions in the
change description:

1. What local ability or runtime contract owns the request?
2. Is the Cloud output a suggestion, analysis result, candidate, or
   `proposal_input`?
3. Which local/Core path owns approval and final write?
4. What abuse categories are denied or manual-review gated?
5. Which smoke or contract test proves Cloud did not become a second control
   plane?

If any answer moves approval, ability truth, workflow truth, prompt/router
truth, or WordPress write authority into Cloud, stop and write a new boundary
proposal before implementation.
