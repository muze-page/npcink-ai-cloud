# Nightly Inspection Cloud/Core Handoff v1

Status: active implementation handoff

Date: 2026-06-16

## Scope

This handoff closes the first production-grade Cloud/Core loop for Pro Nightly
Inspection without introducing a Cloud scheduler or plugin-side Action
Scheduler dependency.

The intended chain is:

1. Toolbox keeps schedule truth locally through WP-Cron and submits a signed
   Pro runtime request to Cloud.
2. Cloud executes `magick-ai-toolbox/analyze-nightly-content-batch` through the
   existing hosted runtime queue and worker.
3. Cloud stores canonical run state in `run_records` and returns polling or
   callback-compatible results.
4. Cloud includes `nightly_site_inspection_result.v1` and, when reviewable
   issues exist, a `nightly_site_inspection_core_review_plan.v1` candidate.
5. Toolbox submits that plan to Core's existing `/proposals/from-plan` route
   using `npcink-toolbox/build-nightly-inspection-review-plan`.
6. Core creates a blocked `create-draft` proposal that preserves Cloud evidence
   and requires human `title` and `content` before commit preflight can pass.

## Boundary

Cloud owns runtime execution, run evidence, quota evidence, terminal result
delivery, and read-only diagnostics.

Cloud does not own WP-Cron schedule truth, local batching policy, Ability
registry truth, Core approval state, proposal truth, commit preflight, or final
WordPress writes.

Core owns proposal intake, approval state, commit preflight, audit, and final
handoff to the adapter after approval.

## Cloud Result Requirements

Cloud must keep the outer hosted runtime result compatible:

- `contract_version`: `cloud_batch_runtime_result.v1`
- `status`: terminal or current hosted runtime status, such as `succeeded`
- `worker_phase`: operator-readable runtime phase, such as `result_ready`
- `execution_kind`: `nightly_site_inspection`
- `runtime_owner`: `npcink-local-automation-runtime`
- `cloud_role`: `runtime_detail`
- `eligibility_summary`: bounded item and reviewability counts for Toolbox
- `blocked_items`: blocked items with reasons, or an empty list
- `review_items`: prioritized operator review items, not raw payload dump
- `operator_next_action`: next operator action, such as
  `review_cloud_batch_result`
- `retryable`: boolean retry guidance for this result state
- `retry_guidance`: bounded retry reason and next action guidance
- `safety.direct_wordpress_write`: `false`
- `safety.final_write_path`: `core_proposal_required`

The additive Morning Brief result uses:

- `nightly_result.contract_version`: `nightly_site_inspection_result.v1`
- `nightly_result.safety.cloud_scheduler_truth`: `false`

The additive Core handoff plan uses:

- `core_review_plan.artifact_type`: `nightly_site_inspection_review_plan`
- `core_review_plan.contract_version`:
  `nightly_site_inspection_core_review_plan.v1`
- `core_review_plan.requires_approval`: `true`
- `core_review_plan.dry_run`: `true`
- `core_review_plan.commit_execution`: `false`
- `core_review_plan.direct_wordpress_write`: `false`
- `core_review_plan.write_actions[0].target_ability_id`:
  `npcink-abilities-toolkit/create-draft`
- `core_review_plan.write_actions[0].proposal_ready`: `false`
- `core_review_plan.write_actions[0].requires_input`: `["title", "content"]`

## Core Intake Requirements

Core accepts only the read-only plan ability:

`npcink-toolbox/build-nightly-inspection-review-plan`

Core must reject the plan when:

- `artifact_type` is not `nightly_site_inspection_review_plan`;
- `contract_version` is present and not
  `nightly_site_inspection_core_review_plan.v1`;
- `direct_wordpress_write` is true;
- `evidence_refs` is empty;
- the plan contains anything other than one blocked `create-draft` action;
- the action is `proposal_ready=true`;
- the action does not require human `title` and `content`;
- the action requests publish, commit, or non-dry-run execution.

## Verification

Cloud:

```bash
cd /Users/muze/gitee/magick-ai-cloud
.venv/bin/pytest tests/api/test_cloud_batch_runtime.py \
  tests/contract/test_nightly_site_inspection_contract.py
```

Core:

```bash
cd /Users/muze/gitee/npcink-governance-core
php tests/run.php
php tests/fail-closed.php
```

Expected outcome:

- Cloud runtime queues and worker result expose the Morning Brief result and
  Core review plan candidate.
- Core creates one blocked proposal for the valid review plan.
- Core rejects ready or evidence-free nightly review plans.
- No test requires Action Scheduler, Cloud scheduler truth, or direct WordPress
  mutation from Cloud.
