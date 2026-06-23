# Cloud Agent Positioning v1

Status: active.
Date: 2026-06-07

## Purpose

This document defines how Npcink AI Cloud should understand and implement
Agent-shaped capabilities without becoming a second control plane, a second
workflow truth, or a cloud-side WordPress write owner.

The working definition is:

`Agent = goal + context + allowed abilities + planning policy + execution loop + guardrails + handoff result`

In Npcink AI Cloud, an Agent is best treated as a bounded runtime mode, not as a
new platform layer.

## Product Positioning

Npcink AI Cloud may support Agentic execution when the Agent remains a
controlled assistant for hosted runtime, analysis, retrieval, diagnostics, and
recommendation work.

Cloud Agents should compose small abilities, but ability composition alone is
not enough to define an Agent. A fixed sequence is a workflow. An Agent adds a
bounded decision loop: it may inspect context, choose the next allowed step,
recover from expected failure, and return a structured handoff.

The product posture is:

`controlled Agentic runtime, not cloud Agent control plane`

For customer-facing Agent scenarios, the differentiating loop is:

`Cloud Agent recommendation + local governance + feedback for Cloud evaluation`

Cloud may improve Agent quality from structured customer review outcomes, but
those outcomes must feed evaluation and recommendation loops before they affect
production behavior. Feedback must not become Cloud-side approval, preflight, or
WordPress write truth. The feedback contract is defined in
[cloud-agent-feedback-contract-v1.md](cloud-agent-feedback-contract-v1.md).

## Boundary

Local WordPress, Core, and the plugin stack remain responsible for:

- ability definitions and schemas
- workflow, proposal, approval, and audit truth
- prompt, preset, and router final enablement truth
- permission gates and write confirmation
- final WordPress object writes

Npcink AI Cloud may be responsible for:

- hosted model execution
- provider routing and fallback execution
- queue-backed whole-run offload
- retrieval or analysis over Cloud-owned read models
- usage, health, diagnostics, and service evidence
- evidence-backed recommendations
- structured `proposal_input` or suggestion handoff payloads
- structured Agent feedback aggregation for evaluation and quality improvement

Cloud must not become responsible for:

- a cloud skill registry
- a cloud MCP platform
- a cloud Agent Gateway product
- a cloud workflow builder
- a cloud prompt or preset editor
- automatic routing profile adoption
- automatic commercial state mutation
- automatic WordPress content, settings, or WooCommerce writes
- automatic production prompt, preset, router, or profile mutation from
  feedback events

## Agent vs Workflow

A workflow is appropriate when the path is fixed:

```text
step A -> step B -> step C -> result
```

An Agent is appropriate when bounded choice is useful:

```text
inspect context
choose one allowed next step
execute through hosted runtime or read model
validate the result
retry, degrade, or stop with evidence
return suggestion, result, or proposal_input
```

The distinction is not marketing copy. It changes the engineering contract:
Agentic execution needs explicit allowed actions, stop conditions, evidence,
storage posture, failure behavior, and handoff shape.

## Allowed First Shapes

### Runtime Agent

Purpose: execute a user-visible hosted model task through the existing runtime
contract.

Input owner: local plugin/Core.

Cloud role:

- resolve hosted profile
- select provider/model within allowed routing rules
- execute the model call
- apply fallback if allowed
- store run status, usage, and result metadata
- return result or callback status

Output posture:

- normal runtime result
- no Cloud-side WordPress write
- local fallback remains available

### Site Knowledge Agent

Purpose: use site knowledge to produce evidence-backed preparation material or
suggestions.

Cloud role:

- search or rerank site knowledge read models
- identify gaps, duplicates, internal link opportunities, or preparation tasks
- produce `suggestion_only` output
- include evidence and confidence
- return `proposal_input` only when local review should create a proposal

Output posture:

- `direct_wordpress_write: false`
- `wordpress_write_owner: wordpress_local`
- final approval and writes stay in Core/local plugin

### Ops Advisor Agent

Purpose: analyze Cloud service evidence for operators or bounded portal detail.

Cloud role:

- summarize runtime, provider, queue, callback, usage, health, and audit signals
- detect likely blockers or anomalies
- recommend next investigation steps
- generate redacted operator summaries or support drafts where allowed

Output posture:

- advisory only
- evidence-backed
- `requires_operator: true` for follow-up actions
- no automatic provider, router, entitlement, billing, or customer state changes

## Required Agent Contract

Every Cloud Agent proposal should define:

- `agent_id`
- `agent_version`
- triggering local ability or runtime contract
- allowed input fields
- allowed tool/read-model actions
- forbidden actions
- execution pattern: `inline` or `whole_run_offload`
- timeout, retry, retention, and storage posture
- evidence requirements
- output shape
- local handoff owner
- fail-closed behavior

Public runtime intake must continue to consume bounded runtime-plane fields.
Local governance, approval, and write policy fields must not move into Cloud
policy ingress.

## Implementation Posture

Do not create a new Agent platform first.

Prefer extending the existing Cloud stack:

```text
local plugin/Core
  -> signed runtime request and execution contract
  -> Cloud /v1/runtime/execute
  -> Cloud runtime service or worker
  -> provider, retrieval, diagnostics, or read-model action
  -> run record, usage, audit, and result metadata
  -> callback or result pull
  -> local proposal, approval, or display
```

The first implementation should reuse:

- FastAPI runtime routes
- existing runtime service and worker patterns
- PostgreSQL run records and usage evidence
- Redis only for wake-up, queue assist, replay, or short-lived coordination
- existing advisor, site-knowledge, diagnostics, and observability read models

Do not introduce Temporal, Celery, Kafka, a second scheduler truth, a second
workflow engine, or an Agent Gateway surface for the first Agentic iteration.

## Recommended Next Step

The safest next step is:

1. Finish the user-visible hosted GPT5.5 text loop through the normal
   runtime/toolbox path.
2. Keep minimum provider, usage, error, and run-status evidence for that loop.
3. Add one narrow Agentic scenario only after the loop is proven.

Recommended first Agentic scenario:

```text
site_knowledge -> suggestion_only -> local proposal
```

Why this first:

- it uses existing Cloud site-knowledge and runtime surfaces
- it creates visible customer value without direct WordPress writes
- it proves evidence-backed composition
- it keeps local Core as proposal, approval, and write owner
- it creates the first measurable Agent quality loop through local review
  feedback

Initial implementation note: Site Knowledge search results expose this as an
additive `agent_handoff` object on the existing runtime response. The handoff
does not create a new `/agents` route, registry, scheduler, workflow engine, or
Cloud-side write authority.

The next extension is structured local feedback, not broader autonomy:

```text
agent_handoff -> local review outcome -> cloud_agent_feedback.v1 -> eval rollup
```

This keeps the Agent optimizable while preserving local governance.

Alternative first scenario:

```text
ops advisor -> evidence-backed next step
```

Why this is also safe:

- it is internal or bounded portal detail
- it reads Cloud-owned operational evidence
- it can be useful before customer-facing Agentic features
- it does not mutate local plugin, router, commercial, or WordPress truth

## Acceptance Checklist

Before shipping any Cloud Agent:

- local truth path remains unchanged
- Cloud output is result, suggestion, recommendation, or `proposal_input`
- WordPress writes require local Core approval/preflight/audit
- no cloud skill, MCP, workflow, prompt, preset, or router control plane is added
- no forbidden infrastructure is introduced
- result storage follows `storage_mode`
- secrets, raw prompts, callbacks, and WordPress content are not exposed through
  advisor or portal detail surfaces
- tests cover forbidden policy/write fields and fail-closed behavior
- any feedback collection follows `cloud_agent_feedback.v1` and feeds eval or
  recommendation first, not automatic production mutation
