# Nightly Inspection Real-Site Operator Trial - 2026-06-17

Status: draft controlled-trial record template.

Purpose: run the Nightly Site Inspection and Morning Brief loop on one or two
real WordPress sites before expanding the product. This document extends the
existing external-trial runbook with Nightly Inspection specific evidence.

This is not a GA launch plan, scheduler plan, or article automation plan.

## Scope

Allowed in this trial:

- Cloud-hosted Nightly Inspection runtime execution;
- deterministic content quality scoring and score breakdown display;
- review-only Morning Brief organization;
- metadata-only operator feedback through the Cloud Agent Feedback contract;
- local WordPress/Core review as the final approval and write owner.

Not allowed in this trial:

- automatic article generation;
- automatic publishing or metadata repair;
- bulk apply or one-click site mutation;
- Cloud-owned scheduling, workflow truth, or WordPress writes;
- widening Action Scheduler or local automation runtime scope.

## Entry Criteria

Start with only one site. Add a second site only after the first site completes
at least three useful inspection cycles without boundary issues.

Required before inviting a site:

- site owner, operator, and support contact are known;
- site category passes the external-trial invite criteria;
- Cloud API key is active and saved in the WordPress addon;
- Toolbox Pro Cloud Runtime controls are visible;
- the operator understands that Morning Brief items are suggestions only;
- the site has enough existing posts/pages to make inspection useful;
- no requirement exists for automatic writing, automatic repair, or scheduled
  unattended publishing.

## Trial Run Template

Create one entry per site and update it after each run.

```markdown
## Trial Site

- Date:
- Operator:
- WordPress site URL:
- Cloud base URL:
- Site ID:
- Account ID:
- Declared use case:
- Site category decision: approved / manual-review / rejected
- Cloud API key verified: yes/no
- Toolbox Pro Cloud Runtime visible: yes/no
- Operator briefed on review-only boundary: yes/no

## Nightly Inspection Runs

| Run date | Cloud run ID | Status | Items scanned | Reviewable | Critical | Warnings | Avg score | Operator reviewed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |  |  |  |

## Morning Brief Review

- Did the priority queue identify the right first items: yes/no/mixed
- Useful issue groups:
- Noisy issue groups:
- Missing context:
- Confusing labels or copy:
- Did the brief save editorial time: yes/no/mixed
- Did the operator need Core handoff: yes/no
- Any attempted Cloud write or direct mutation: yes/no

## Feedback Loop

- Feedback events submitted: yes/no
- Accepted items:
- Rejected items:
- Wrong priority labels:
- Already handled labels:
- Evidence weak labels:
- Wrong next step labels:
- Top rejected reason codes:
- Feedback summary checked in Cloud: yes/no

## Boundary Review

- WordPress direct write absent: yes/no
- Cloud article generation absent: yes/no
- Bulk article generation absent: yes/no
- Local/Core final approval owner preserved: yes/no
- Secrets, cookies, nonces, or passwords absent from feedback: yes/no
- Any support or abuse concern:

## Decision

- Go/no-go:
- Continue unchanged / adjust scoring / adjust Morning Brief copy / pause site:
- Follow-up implementation task:
- Weekly review notes:
```

## Minimum Evidence Commands

Run these before the first site starts and again before expanding beyond one
site:

```bash
make lint-changed
.venv/bin/pytest tests/api/test_cloud_batch_runtime.py tests/api/test_agent_feedback_routes.py tests/contract/test_nightly_site_inspection_contract.py
pnpm run check:agent-feedback-quality
```

Record the Toolbox companion evidence from the WordPress addon repository:

```bash
composer smoke:nightly-inspection-cloud-ui
composer smoke:nightly-inspection-cloud-batch-merge
composer test:all
```

## Weekly Review Questions

Review at least three completed runs before changing scoring weights, grouping,
copy, or prioritization:

- Which reason codes consistently produced useful review items?
- Which reason codes produced noisy or already-handled items?
- Did score breakdown help the operator trust the recommendation?
- Did the Morning Brief reduce morning review time?
- Did any operator expect Cloud to publish or repair content?
- Did feedback labels show a bounded improvement path?

If the answer points toward Cloud owning approval, scheduling, publishing,
prompt truth, workflow truth, ability truth, or WordPress writes, stop and open
a separate boundary proposal before implementing anything.
