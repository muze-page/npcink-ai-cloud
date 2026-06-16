# Nightly Inspection Stage Closeout 2026-06-16

Status: current stage closed

Date: 2026-06-16

## Purpose

This document summarizes the historical decisions, implementation scope,
verification evidence, and next-stage boundary for the Nightly Site Inspection
work across Magick AI Cloud, Toolbox, and Governance Core.

The product framing is fixed as:

`nightly site inspection + morning writing preparation + content quality scoring`

It must not be presented as nightly automatic article writing, hands-free
publishing, or a Cloud-owned editorial workflow.

## Historical Summary

The work started from a product question: whether the nightly execution plan
should use local `WP-Cron` for the basic edition and Cloud orchestration for the
advanced edition.

The accepted split evolved into:

- Basic: local WordPress fallback preview using `WP-Cron`.
- Pro: Cloud Batch Runtime for reliable queued analysis execution.
- Agency: future read-only multi-site summary surfaces only.

During the discussion, plugin-side Action Scheduler was explicitly considered
and rejected for the current Basic and Pro paths. The reason was not that Action
Scheduler is technically unsuitable in general, but that it would create a
second local queue, claim, retry, table, and recovery surface inside the
WordPress plugin. Pro reliability belongs in Cloud Batch Runtime for this
phase.

The team also clarified that `npcink-local-automation-runtime` is the future
owner for unattended and bulk local automation. That owner boundary avoids
turning Toolbox, Core, or Cloud into hidden workflow engines.

## Decisions

### Basic Edition

Basic uses WordPress-side `WP-Cron` only as a disabled-by-default local fallback
preview.

It may:

- collect a bounded public content snapshot;
- score deterministic content quality signals;
- store one latest dry-run preview option;
- show a review-only Morning Brief.

It must not:

- call Cloud;
- create Core proposals;
- use Action Scheduler;
- create custom runtime tables;
- create lease, retry, or dead-letter processors;
- write WordPress content.

### Pro Edition

Pro uses Cloud Batch Runtime.

Toolbox keeps local schedule truth and submits bounded site evidence to Cloud.
Cloud accepts the signed runtime request, queues the run, executes through the
existing worker, stores run evidence, meters usage, and returns a reviewable
result.

The first supported runtime ability is:

`magick-ai-toolbox/analyze-nightly-content-batch`

The Cloud result uses:

- `cloud_batch_runtime_result.v1`
- `nightly_site_inspection_result.v1`
- `nightly_site_inspection_core_review_plan.v1`

### Core Handoff

Cloud may attach a Core review-plan candidate, but it does not create a final
article plan and does not create or approve proposals itself.

Core accepts only the bounded plan ability:

`npcink-toolbox/build-nightly-inspection-review-plan`

Core creates one blocked `npcink-abilities-toolkit/create-draft` proposal when
the plan is valid. The proposal remains not ready until a human supplies
`title` and `content`.

Core rejects the plan when it is ready-to-write, evidence-free, non-dry-run,
direct-write capable, or does not require human title/content input.

### Cloud Boundary

Cloud owns runtime execution detail only.

Cloud may own:

- signed runtime request acceptance;
- queue-backed run execution;
- PostgreSQL run evidence;
- usage, quota, and entitlement evidence;
- provider-call evidence;
- polling or callback-compatible terminal result delivery;
- read-only diagnostics.

Cloud must not own:

- WordPress schedule truth;
- local batch fan-out policy;
- Ability registry truth;
- Core proposal truth;
- approval state;
- commit preflight;
- final WordPress writes;
- a second scheduler truth;
- a second workflow engine.

## Implemented Components

### Magick AI Cloud

Implemented:

- Cloud Batch Runtime contract and service.
- Runtime integration through `POST /v1/runtime/execute`.
- Ability defaults for `automation`, `nightly_site_inspection`,
  `cloud-batch-runtime.managed`, and `whole_run_offload`.
- Queue-backed worker execution through the existing runtime worker.
- Result generation with review-only content quality signals.
- Core review-plan candidate generation.
- Batch item cap and commercial package limit handling.
- Pro Cloud Runtime entitlement detail through the existing entitlement
  surface.
- Tests for runtime execution, entitlement, quota, and boundary contracts.

Key files:

- `app/domain/cloud_batch_runtime/contracts.py`
- `app/domain/cloud_batch_runtime/service.py`
- `app/domain/runtime/service.py`
- `app/api/routes/runtime.py`
- `app/api/routes/entitlements.py`
- `tests/api/test_cloud_batch_runtime.py`
- `tests/contract/test_nightly_site_inspection_contract.py`
- `tests/api/test_entitlement_routes.py`

### Magick AI Toolbox

Implemented in the sibling Toolbox repository:

- Phase 2 Basic WP-Cron dry-run preview.
- Nightly Inspection snapshot collector, deterministic builder, and manual
  planner.
- Cloud Batch result merger.
- Pro Cloud Runtime operator UI on the Toolbox Start surface.
- Cloud entitlement refresh.
- Cloud batch submit, status polling, result loading, and merged Morning Brief
  display.
- Boundary smoke coverage that blocks Action Scheduler, local runtime tables,
  Cloud scheduler truth, automatic Core proposal creation, and WordPress writes.

The verified UI exposes:

- `Local Fallback Preview`
- `Enable local WP-Cron fallback preview`
- `Enable Pro Cloud Runtime controls`
- `Run Cloud inspection`
- `Refresh Cloud quota`
- `Merged preview`
- `Run status`
- `Worker phase`
- `Core handoff`

### Governance Core

Implemented in the sibling Core repository:

- `npcink-toolbox/build-nightly-inspection-review-plan` allowlisted plan intake.
- Contract validation for
  `nightly_site_inspection_core_review_plan.v1`.
- Blocked `create-draft` proposal creation that preserves Cloud evidence.
- Fail-closed rejection for ready, evidence-free, direct-write, publish,
  commit, and non-dry-run plans.
- Admin-only `GET /wp-json/npcink-governance-core/v1/contract` discovery
  endpoint.

Merged Core PRs relevant to this stage:

- `#19` Accept nightly inspection review plans.
- `#20` Block theme profile contract cleanup, already merged before the final
  closeout.
- `#21` Add Core runtime contract endpoint.

## Verification Evidence

### Cloud

Full Cloud test suite:

```bash
cd /Users/muze/gitee/magick-ai-cloud
.venv/bin/pytest
```

Result:

```text
499 passed, 6 skipped
```

Targeted Nightly Inspection tests:

```bash
.venv/bin/pytest tests/api/test_cloud_batch_runtime.py \
  tests/contract/test_nightly_site_inspection_contract.py \
  tests/api/test_entitlement_routes.py
```

Result:

```text
12 passed
```

### Toolbox

Default Toolbox test gate:

```bash
cd /Users/muze/gitee/magick-ai-toolbox
composer test:all
```

Result:

```text
passed
```

The gate includes:

- local automation runtime replay smoke;
- negative replay drift checks;
- Nightly Site Inspection replay fixture;
- builder smoke;
- manual planner smoke;
- snapshot preview smoke;
- Basic WP-Cron dry-run smoke;
- Cloud Batch merge smoke;
- Cloud Runtime UI contract smoke;
- orchestration boundary smoke.

Real WordPress plus Cloud E2E smoke:

```bash
composer smoke:nightly-inspection-cloud-e2e
```

Latest result:

```text
Nightly inspection Cloud Batch E2E smoke passed: run_91d55db8f43043a48d6136ee6b3d76b2
```

Earlier operator UI validation also produced:

```text
run_a33f502bcf484c57b0daaf20c8a0e43b
status: Succeeded
worker phase: Terminal
merged preview: 15 local priority matches
writes: None
```

### Core

Core default test gate:

```bash
cd /Users/muze/gitee/npcink-governance-core
composer test:all
```

Result:

```text
PHP lint: ok
Static contracts: ok
Fail-closed fault injection: ok
```

Additional targeted commands used during closeout:

```bash
php -l includes/Rest/Contract_Controller.php
php tests/run.php
php tests/fail-closed.php
git diff --check
```

Result:

```text
all passed
```

## Repository State At Closeout

At closeout, the three repositories were clean and tracking GitHub master:

- `/Users/muze/gitee/magick-ai-cloud`
- `/Users/muze/gitee/magick-ai-toolbox`
- `/Users/muze/gitee/npcink-governance-core`

Each reported:

```text
## master...origin/master
```

Gitee was removed from the Cloud repository's local remotes after the GitHub
migration. GitHub is the intended source of project management going forward.

## Current Capability

The current stage is locally usable for development and operator trial:

1. Toolbox can show the Pro Cloud Runtime controls.
2. Toolbox can refresh Cloud quota and submit a Cloud inspection.
3. Cloud accepts and queues the request.
4. The Cloud worker processes the run to `succeeded`.
5. Toolbox can poll/read the Cloud result.
6. Toolbox can merge the result into a review-only Morning Brief preview.
7. The UI preserves the boundary that Cloud review items have no direct writes.
8. Core can accept the review-plan candidate only as a blocked proposal path.

This is enough to stop feature expansion for the current stage.

## Known Limits

The feature is not yet a production launch.

Known limits:

- The current validation is local development and local WordPress E2E, not a
  public production deployment proof.
- The scoring is intentionally conservative and deterministic-first.
- The Morning Brief may still need real editor feedback to reduce noise.
- Cloud Agency read-only aggregation is not implemented in this stage.
- Cloud must not be expanded into autonomous scheduling or article drafting as
  part of this feature.
- Action Scheduler remains deferred as a future local fallback/substrate
  candidate only if a confirmed local-batch requirement appears.

## Next Stage

Do not broaden the feature set yet.

The next stage should only deepen the already-working inspection loop:

1. scoring dimension optimization;
2. Morning Brief information organization;
3. real-site feedback loop.

This keeps the work focused on whether the feature saves editorial time, not on
building a heavier automation platform.

### 1. Scoring Dimension Optimization

Goal: make the content quality score more useful without making it opaque or
turning it into an unattended SEO promise.

The current score is deterministic-first and based on bounded metadata signals.
The next version may refine it into a visible `score_breakdown` with stable
dimensions such as:

- metadata completeness: title length, meta description presence and length;
- content depth: word count and thin-content signals;
- freshness: age since last meaningful update;
- internal navigation: internal link count and missing link opportunities;
- media accessibility: missing image alt text;
- editorial opportunity: whether the issue is a refresh, repair, or review
  candidate.

Implementation rules:

- keep reason codes stable and test-covered;
- keep each score tied to supplied evidence;
- expose weights or severity mapping in a contract or fixture;
- prefer deterministic signals before model-assisted explanation;
- let Cloud compute runtime detail, but not own editorial truth;
- let Toolbox display score breakdown and priority;
- let Core consume only the bounded review-plan candidate.

Do not add:

- hidden LLM-only scoring with no evidence;
- traffic, ranking, or revenue guarantees;
- automatic article generation;
- automatic metadata repair;
- direct WordPress writes.

Expected outputs:

- clearer severity thresholds;
- a per-action score breakdown;
- reason-code weighting fixtures;
- contract tests that freeze the new fields and write-denial boundary.

Initial implementation now exists in Cloud as
`nightly_content_quality_score.v2`. It adds a visible action-level
`score_breakdown`, a result-level `scoring_profile`, deterministic reason
weights, and contract tests for the write-denial boundary.

### 2. Morning Brief Information Organization

Goal: make the morning review surface easier to scan and act on.

The Morning Brief should organize inspection results around editorial decisions,
not raw technical defects. A useful structure is:

- top summary: items scanned, reviewable items, warnings, critical items,
  average score;
- priority queue: the few items that deserve attention first;
- grouped issues: metadata, thin content, internal links, media accessibility,
  stale content;
- writing preparation: evidence, suggested review angle, missing context, and
  next local action;
- Core handoff status: whether a blocked proposal candidate is available and
  what human input is still required.

Implementation rules:

- keep the brief review-only;
- keep generated language short and evidence-linked;
- show why an item is prioritized;
- avoid long article outlines, paragraphs, final FAQ copy, or final SEO copy;
- keep the operator next action explicit: review, ignore, prepare Core handoff,
  or gather more context.

Expected outputs:

- fewer noisy items at the top;
- clearer group labels and action labels in Toolbox;
- a stable result shape that can be smoke-tested with replay fixtures;
- no change to final approval or WordPress write ownership.

Initial implementation now exists in Cloud as
`nightly_site_inspection_morning_brief.v2`. It adds `top_summary`,
`priority_queue`, `issue_groups`, enriched `writing_preparation`, and
`core_handoff` status while preserving the existing `actions` result for
Toolbox compatibility.

### 3. Real-Site Feedback Loop

Goal: learn from actual operator decisions before expanding the product.

Start with one or two real WordPress sites and run several inspection cycles.
For each Morning Brief item, capture lightweight operator feedback such as:

- accepted;
- rejected;
- wrong priority;
- weak evidence;
- duplicate or already handled;
- wrong next step;
- operator confidence high or low.

The existing Cloud Agent Feedback pattern is the preferred shape for this loop:
Cloud may accept signed feedback events and provide read-only quality rollups,
while local WordPress remains the truth for approval, preflight, final writes,
and object mutation.

Implementation rules:

- feedback must reference a `run_id`, action id, object id, or evidence ref;
- feedback must be idempotent;
- feedback must not include secrets, cookies, nonces, passwords, or write
  authority fields;
- Cloud feedback summaries remain read-only quality evidence;
- feedback may tune reason-code weighting after review, but must not mutate live
  WordPress content.

Expected outputs:

- acceptance and rejection rate by reason code;
- low-quality label summaries;
- examples of noisy or useful Morning Brief items;
- a short operator-trial note before any larger product expansion.

Initial implementation now reuses Cloud Agent Feedback with
`source_runtime: nightly_site_inspection`. The feedback event may carry source
action id, object id, reason codes, source score, and source severity. The
summary response now includes a read-only `nightly_inspection` rollup for
accepted/rejected outcomes, wrong-priority labels, already-handled labels,
rejected reason codes, severities, and average source score.

### Explicitly Deferred

The next stage should still not implement:

- Action Scheduler for Pro;
- custom local runtime tables;
- `npcink-local-automation-runtime` as a new plugin;
- automatic article writing;
- automatic repair or one-click bulk apply;
- multi-channel morning delivery;
- Agency multi-site aggregation;
- a Cloud scheduler, workflow engine, or second control plane.

These may be revisited only after the single-site review loop proves that the
Morning Brief is useful and that the remaining pain is operational rather than
scoring or information-organization quality.

### Trial Checklist

1. Select one or two real WordPress sites.
2. Run Nightly Inspection several times with realistic content.
3. Review whether the Morning Brief saves editorial time.
4. Track which signals are useful and which are noise.
5. Adjust scoring, copy, or prioritization only after feedback.

## Final Boundary Reminder

The stage closes with this rule:

Local WordPress owns schedule, review, approval, and final writes. Cloud owns
bounded runtime execution and evidence. Core owns proposal truth, approval,
preflight, and audit. Toolbox is the operator surface and bridge.

No part of this feature should silently become an automatic article writer, a
second scheduler truth, or a second WordPress write owner.
