# Cloud Agent Feedback Contract v1

Status: active.
Date: 2026-06-07

## Purpose

This document defines the feedback loop for Cloud Agent recommendations.

The product posture is:

`Cloud Agent recommendation + local governance + feedback for Cloud evaluation`

This is the differentiation loop for Magick AI Cloud: Cloud can improve its
recommendation quality from customer review signals, while the customer site
keeps approval, preflight, audit, and final WordPress writes local.

## Boundary

Cloud may collect bounded feedback about Agent recommendations for:

- quality evaluation
- evidence ranking
- prompt and profile improvement
- routing and fallback assessment
- offline eval set construction
- aggregate product fit measurement

Cloud must not use feedback as:

- approval truth
- preflight truth
- WordPress write authority
- automatic prompt, preset, router, or profile adoption truth
- automatic customer-site configuration mutation
- a second workflow, ability, skill, MCP, or OpenClaw control plane

Local WordPress/Core remains the owner of:

- proposal state
- approval and rejection decisions
- execution preflight
- audit trail for local writes
- final WordPress object writes
- user-visible adoption of any generated content

## Feedback Event Shape

The first contract is the event shape. The initial signed API surface is:

```text
POST /v1/agent-feedback/events
```

The route requires normal site HMAC authentication, `runtime:execute` scope, and
an `Idempotency-Key`. It accepts one `cloud_agent_feedback.v1` event and records
it as eval/quality metadata. It must not mutate production prompts, profiles,
routers, proposals, approvals, preflight, or WordPress content.

```json
{
  "contract_version": "cloud_agent_feedback.v1",
  "site_id": "site_123",
  "agent_id": "site_knowledge_suggestion_agent",
  "agent_version": "2026-06-07",
  "source_runtime": "site_knowledge",
  "source_run_id": "run_123",
  "handoff_id": "handoff_123",
  "handoff_type": "proposal_input",
  "local_surface": "toolbox_site_knowledge",
  "local_outcome": "edited_before_accept",
  "feedback_labels": [
    "evidence_useful",
    "missing_context"
  ],
  "operator_note": "Evidence was useful, but the final draft title needed a narrower topic.",
  "local_proposal_id": "proposal_123",
  "evidence_ref_ids": [
    "post:123"
  ],
  "created_at": "2026-06-07T00:00:00Z"
}
```

Required fields:

- `contract_version`
- `site_id`
- `agent_id`
- `source_runtime`
- `handoff_type`
- `local_surface`
- `local_outcome`
- `created_at`

Optional fields:

- `agent_version`
- `source_run_id`
- `handoff_id`
- `feedback_labels`
- `operator_note`
- `local_proposal_id`
- `evidence_ref_ids`
- `redaction_status`
- `retention_class`

The initial route returns a receipt with local-truth markers:

- `accepted_for_eval=true`
- `quality_rollup_candidate=true`
- `production_mutation=false`
- `approval_truth=wordpress_local`
- `preflight_truth=wordpress_local`
- `final_write_truth=wordpress_local`

## Allowed Outcomes

`local_outcome` must be one of:

- `accepted`
- `rejected`
- `edited_before_accept`
- `ignored`
- `expired`
- `blocked_by_policy`
- `blocked_by_missing_input`

These outcomes describe local review state. They do not authorize Cloud to
execute, approve, publish, or mutate the customer site.

## Allowed Feedback Labels

`feedback_labels` may include:

- `evidence_useful`
- `evidence_weak`
- `wrong_intent`
- `wrong_next_step`
- `missing_context`
- `wrong_priority`
- `already_handled`
- `unsafe_or_overreaching`
- `too_generic`
- `duplicate_suggestion`
- `good_but_needs_human_draft`
- `not_relevant_to_site`
- `source_or_license_risk`
- `visual_quality_low`
- `operator_confidence_high`
- `operator_confidence_low`

Labels should be additive. Do not overload one label to mean both quality and
governance state.

## Data Handling

The feedback loop has three data classes.

### Aggregate Safe

May be aggregated across tenants after normal telemetry privacy controls:

- outcome counts
- label counts
- agent id and version
- source runtime
- handoff type
- coarse local surface
- redaction status
- acceptance and rejection rates

### Tenant Scoped

Must remain tenant/site scoped unless explicitly anonymized:

- source run id
- handoff id
- local proposal id
- evidence reference ids
- per-site outcome history
- per-site quality trends

### Sensitive Or Local Only

Must not be used as default cross-tenant training data:

- raw WordPress content
- private content
- customer secrets
- unredacted operator notes
- raw prompt text when it includes site-private details
- final edited post content

If operator notes are sent to Cloud, they must be treated as tenant-scoped
quality feedback by default. Cross-tenant use requires redaction or explicit
aggregation.

## Eval Use

Feedback should enter Cloud optimization through an eval path, not direct
production mutation.

Allowed first use:

```text
feedback event
  -> redaction / classification
  -> aggregate quality rollup
  -> offline eval set candidate
  -> prompt/profile/routing recommendation
  -> human or local adoption review
```

Forbidden shortcut:

```text
feedback event
  -> automatic production prompt change
  -> automatic router/profile adoption
  -> automatic WordPress write
```

Cloud may recommend improvements, but local or operator-controlled review must
decide whether a changed prompt, profile, router, or workflow contract is
adopted.

## Site Knowledge First Scenario

The first recommended feedback loop is:

```text
Cloud Site Knowledge Agent
  -> evidence-backed agent_handoff
  -> Toolbox review
  -> Core blocked proposal or local rejection
  -> structured feedback event
  -> Cloud eval and quality rollup
```

This scenario is valuable because it tests all differentiating parts without
moving final write control:

- Cloud does retrieval, evidence selection, and next-step recommendation.
- Toolbox shows the recommendation and feedback options.
- Core keeps proposal, approval, preflight, and write governance.
- Cloud learns from review outcomes through aggregate evaluation signals.

## Minimal Product Metrics

For the first version, measure:

- handoff shown count
- local proposal submitted count
- accepted count
- edited-before-accept count
- rejected count
- evidence useful rate
- evidence weak rate
- wrong intent rate
- unsafe or overreaching rate

These are product-fit metrics for the Agent. They are not approval or execution
truth.

## Acceptance Checklist

Before implementing a Cloud Agent feedback route or worker:

- feedback event shape follows this contract
- local approval/write truth remains unchanged
- raw WordPress content is not required for aggregate quality metrics
- operator notes are tenant-scoped or redacted before aggregation
- feedback enters eval/recommendation, not automatic production mutation
- tests reject forbidden fields that try to carry approval, preflight, or write
  authority
- no new workflow engine, scheduler truth, skill registry, MCP platform, or
  Agent Gateway surface is introduced
