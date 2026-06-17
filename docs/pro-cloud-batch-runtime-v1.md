# Pro Cloud Batch Runtime v1

Status: active implementation contract

Date: 2026-06-16

## Purpose

Pro Cloud Batch Runtime lets paid sites offload bounded nightly analysis work to
Magick AI Cloud without moving schedule truth, editorial workflow truth, or
WordPress write authority out of the local stack.

The first supported profile is:

`nightly site inspection + morning writing preparation + content quality scoring`

This is not a cloud scheduler, a workflow engine, or an automatic article
writer.

## Ownership Boundary

Local WordPress owns:

- WP-Cron schedule truth and enablement;
- site enumeration and batching policy;
- `npcink-local-automation-runtime` as the future owner for unattended and bulk
  local automation;
- Morning Brief persistence and display;
- user review, Core proposal creation, approval, preflight, apply, audit, and
  rollback;
- all final WordPress writes.

Magick AI Cloud owns:

- signed runtime request acceptance for provisioned active sites;
- queue-backed execution through the existing hosted runtime worker;
- PostgreSQL run evidence through existing `run_records`;
- provider-call/usage evidence for the runtime action;
- polling or callback-compatible terminal result delivery;
- read-only diagnostics.

Cloud must not own:

- WP-Cron schedule truth;
- local batch fan-out policy;
- Core proposal approval state;
- Ability registry or runtime template truth;
- direct WordPress publishing or mutation APIs.

## Runtime Ability

Use the existing public runtime route:

`POST /v1/runtime/execute`

Supported ability names:

- `magick-ai-toolbox/analyze-nightly-content-batch`
- `magick-ai-cloud/analyze-nightly-content-batch`

Defaults:

- `contract_version`: `cloud_batch_runtime_request.v1`
- `ability_family`: `automation`
- `execution_kind`: `nightly_site_inspection`
- `profile_id`: `cloud-batch-runtime.managed`
- `execution_pattern`: `whole_run_offload` for Pro batches
- `storage_mode`: `result_only`
- `data_classification`: `internal`
- `task_backend.callback_mode`: `polling_preferred`

Small diagnostic runs may use `inline`, but product Pro batch flows should use
`whole_run_offload`.

## Request Shape

The request input is site-scoped evidence, not write instructions:

```json
{
  "contract_version": "cloud_batch_runtime_request.v1",
  "task_profile": "nightly_site_inspection_morning_brief",
  "items": [
    {
      "object_type": "post",
      "object_id": 123,
      "title": "Existing title",
      "meta_description": "",
      "word_count": 420,
      "internal_link_count": 0,
      "image_alt_missing": 2,
      "days_since_modified": 430
    }
  ],
  "direct_wordpress_write": false
}
```

Cloud validates the input and rejects secret, approval, or write-control fields,
including `update_post`, `final_write_policy`, `wordpress_write`,
`approval_token`, `nonce`, `cookie`, `password`, and secret-bearing keys.

The first implementation caps each runtime request at 50 content items.
Commercial package metadata may set a lower `max_batch_items` value. When that
value is positive, Cloud rejects oversized Pro batch requests before queueing
the run. During internal development, an omitted or `0` value means the package
does not block on this limit while usage evidence is still recorded.

## Pro Entitlement And Quota

Pro Cloud Batch Runtime is entitlement-backed runtime detail, not a local
scheduler. The Cloud commercial layer may enforce these package metadata fields:

```json
{
  "max_batch_items": 25,
  "nightly_inspection_runs_per_period": 30,
  "nightly_inspection_retention_days": 14,
  "nightly_inspection_payload_modes": ["metadata_only", "excerpt"]
}
```

Rules:

- `nightly_inspection_runs_per_period` counts accepted `automation` runs with
  `execution_kind: nightly_site_inspection` in the active billing period.
- Positive values are enforced fail-closed before a new run is created.
- `0` or omitted values keep the current internal-development posture: no
  package-limit block, but usage metering and audit remain active.
- `nightly_inspection_retention_days` is customer-visible retention guidance for
  result detail; request-level `retention_ttl` still remains bounded by runtime
  contract validation.
- These fields do not grant WordPress write authority and do not move local
  schedule, proposal, approval, or final write truth to Cloud.

## Result Shape

Cloud returns a reviewable result:

```json
{
  "contract_version": "cloud_batch_runtime_result.v1",
  "status": "succeeded",
  "worker_phase": "result_ready",
  "execution_kind": "nightly_site_inspection",
  "runtime_owner": "npcink-local-automation-runtime",
  "cloud_role": "runtime_detail",
  "summary": {
    "items_scanned": 2,
    "actions_total": 1,
    "warning_total": 1,
    "critical_total": 0,
    "average_score": 82.5,
    "score_version": "nightly_content_quality_score.v2"
  },
  "eligibility_summary": {
    "items_total": 2,
    "eligible_count": 2,
    "blocked_count": 0,
    "reviewable_count": 1,
    "selected_count": 1
  },
  "blocked_items": [],
  "review_items": [
    {
      "action_id": "action_001",
      "object_type": "post",
      "object_id": "123",
      "priority_reason": "warning_score",
      "group_ids": ["metadata"],
      "direct_wordpress_write": false
    }
  ],
  "operator_next_action": "review_cloud_batch_result",
  "retryable": false,
  "retry_guidance": {
    "retryable": false,
    "reason": "terminal_result_available",
    "operator_next_action": "review_cloud_batch_result"
  },
  "scoring_profile": {
    "score_version": "nightly_content_quality_score.v2",
    "editorial_truth": "wordpress_local"
  },
  "actions": [
    {
      "action_type": "content_quality_signal",
      "object_type": "post",
      "object_id": "123",
      "score": 67,
      "score_version": "nightly_content_quality_score.v2",
      "score_breakdown": {
        "overall_score": 67,
        "dimensions": [
          {
            "id": "metadata_completeness",
            "score": 86,
            "impact": 14,
            "reason_codes": ["missing_meta_description"]
          }
        ]
      },
      "severity": "warning",
      "reason_codes": ["missing_meta_description"],
      "priority_reason": "warning_score",
      "recommended_next_action": "review_update_brief",
      "direct_wordpress_write": false,
      "status": "succeeded"
    }
  ],
  "nightly_result": {
    "contract_version": "nightly_site_inspection_result.v1",
    "issue_groups": [
      {
        "id": "metadata",
        "label": "Metadata",
        "count": 1,
        "reason_codes": ["missing_meta_description"]
      }
    ],
    "safety": {
      "direct_wordpress_write": false,
      "requires_local_review": true,
      "cloud_scheduler_truth": false
    }
  },
  "morning_brief": {
    "contract_version": "nightly_site_inspection_morning_brief.v2",
    "organization_version": "morning_brief_review_queue.v1",
    "top_summary": {
      "items_scanned": 2,
      "reviewable_items": 1,
      "warnings": 1,
      "critical": 0,
      "average_score": 82.5
    },
    "priority_queue": [
      {
        "action_id": "action_001",
        "object_type": "post",
        "object_id": "123",
        "priority_reason": "warning_score",
        "group_ids": ["metadata"],
        "direct_wordpress_write": false
      }
    ],
    "core_handoff": {
      "available": true,
      "proposal_created": false,
      "requires_input": ["title", "content"]
    }
  },
  "core_review_plan": {
    "artifact_type": "nightly_site_inspection_review_plan",
    "contract_version": "nightly_site_inspection_core_review_plan.v1",
    "requires_approval": true,
    "dry_run": true,
    "commit_execution": false,
    "direct_wordpress_write": false,
    "evidence_refs": [
      {
        "action_id": "action_001",
        "post_id": "123",
        "source_type": "post",
        "reason_codes": ["missing_meta_description"]
      }
    ],
    "write_actions": [
      {
        "action_id": "review_nightly_site_inspection",
        "target_ability_id": "npcink-abilities-toolkit/create-draft",
        "proposal_ready": false,
        "requires_input": ["title", "content"],
        "input": {
          "title": "",
          "content": "",
          "status": "draft",
          "dry_run": true,
          "commit": false
        }
      }
    ]
  },
  "safety": {
    "direct_wordpress_write": false,
    "final_write_path": "core_proposal_required",
    "article_body_generated": false,
    "article_write_plan_generated": false,
    "requires_local_review": true
  },
  "handoff": {
    "target_owner": "magick-ai-core",
    "target_plan_ability_id": "npcink-toolbox/build-nightly-inspection-review-plan",
    "target_plan_contract": "nightly_site_inspection_core_review_plan.v1",
    "core_intake_package_available": true,
    "proposal_created": false,
    "proposal_candidate_available": true,
    "operator_next_action": "review_cloud_batch_result"
  },
  "core_intake_package": {
    "artifact_type": "nightly_site_inspection_core_intake_package",
    "contract_version": "nightly_site_inspection_core_intake_package.v1",
    "available": true,
    "user_action": "select_review_item_in_morning_brief",
    "selected_review_item_ids": ["action_001"],
    "handoff_owner": "wordpress_toolbox_local",
    "handoff_surface": "morning_brief_review_queue",
    "target_owner": "magick-ai-core",
    "target_route": "core:/proposals/from-plan",
    "target_plan_ability_id": "npcink-toolbox/build-nightly-inspection-review-plan",
    "target_plan_contract": "nightly_site_inspection_core_review_plan.v1",
    "proposal_created": false,
    "proposal_state_owner": "magick-ai-core",
    "approval_truth": "wordpress_local",
    "final_write_truth": "wordpress_local",
    "cloud_role": "runtime_detail",
    "cloud_scheduler_truth": false,
    "direct_wordpress_write": false,
    "receipt_expectation": {
      "expected_local_receipt": "core_proposal_id",
      "receipt_owner": "wordpress_toolbox_local",
      "cloud_receipt_storage": "not_canonical"
    }
  }
}
```

The result may contain quality signals, score breakdowns, issue grouping,
review-queue organization, writing preparation evidence, and a Core review-plan
candidate. The top-level operational fields are for Toolbox and operators to
show status, eligibility, blocked items, review items, and retry guidance
without reading raw payloads. They do not grant retry execution, scheduler
truth, proposal creation, approval, or WordPress write authority. The review
plan is not a final article plan. It targets Core proposal intake through
`npcink-toolbox/build-nightly-inspection-review-plan`, remains
`proposal_ready=false`, and requires a human to supply `title` and `content`
before commit preflight can pass. It must not contain long-form article bodies,
cloud-produced article write plans, final SEO copy, or final WordPress writes.
The `core_intake_package` is the Morning Brief selection envelope for local
Toolbox/Core submission. It is not a Cloud-owned proposal receipt; the
canonical receipt remains the local Core `core_proposal_id` after Toolbox
submits the selected review item through `/proposals/from-plan`.

Scoring v2 keeps the score explainable by exposing deterministic dimensions:

- metadata completeness;
- content depth;
- freshness;
- internal navigation;
- media accessibility;
- editorial opportunity.

Each action-level `score_breakdown` must stay tied to supplied evidence and
reason codes. Cloud may compute this runtime detail, but editorial acceptance,
proposal creation, approval, and final writes remain local.

Real-site operator feedback should use the existing Cloud Agent Feedback
contract with `source_runtime: nightly_site_inspection`. Feedback may include
the source action id, object id, reason codes, source score, and source
severity. Cloud may summarize accepted/rejected rates, wrong-priority labels,
already-handled labels, and rejected reason codes as read-only quality evidence.
It must not use feedback to mutate WordPress content or bypass local review.

## MVP Implementation

The v1 MVP intentionally reuses the hosted runtime system:

- public HMAC auth and scopes from runtime routes;
- idempotency through `site_id + idempotency_key`;
- `run_records` as canonical run state;
- Redis/in-memory queue only as worker wake-up;
- `RuntimeService.process_queued_runs` as the worker entry;
- `/v1/runs/{run_id}` and `/v1/runs/{run_id}/result` for polling.

No Action Scheduler dependency is required in the plugin for the Pro path.
No new Cloud scheduler or orchestration framework is introduced.

Toolbox can read current Pro Cloud Runtime status through:

```http
GET /v1/entitlements/current?object_type=site&object_id={site_id}
```

The response includes `entitlement.pro_cloud_runtime` with the feature id,
period limit, used and remaining run counts, batch item cap, result retention
days, payload modes, and a `local_truth` block that keeps schedule ownership,
runtime ownership, Core proposal handoff, and direct-write denial explicit.

## Future Extensions

Future versions may add richer model-assisted explanations, per-action metrics,
and read-only Agency summaries, but only if they preserve this boundary:

local owns control and writes; Cloud owns bounded runtime execution and evidence.
