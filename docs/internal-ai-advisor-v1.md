# Internal AI Advisor v1

Status: active
Date: 2026-06-04

## Scope

Internal AI Advisor defines how Magick AI Cloud may use AI for our own cloud
operations, analytics, diagnostics, and recommendations.

This contract does not define customer-facing AI features, a second product
control plane, a workflow engine, a router editor, a prompt editor, billing
automation, or WordPress writes.

## Boundary

Internal AI Advisor is an advisory read layer over Cloud service evidence.
Cloud may summarize, rank, explain, and recommend based on existing operational
data. It must not become the owner of local plugin truth, routing truth, prompt
truth, entitlement truth, approval truth, or WordPress write truth.

Allowed:

- summarize runtime, provider, queue, callback, health, usage, billing,
  entitlement, audit, and plugin-observability evidence
- detect anomalies and support attention items
- recommend operator follow-up steps
- recommend hosted routing, provider, model, or entitlement review candidates
- generate internal support drafts from redacted operational evidence
- generate eval, canary, and upgrade recommendations for operator review

Forbidden:

- automatically mutate WordPress content, settings, WooCommerce data, or local
  plugin configuration
- automatically adopt routing profiles, prompts, presets, workflows, abilities,
  MCP tools, or OpenClaw projections
- automatically create, rotate, revoke, upgrade, downgrade, charge, refund, or
  cancel customer commercial state
- expose raw prompts, completions, generated content, secrets, request payloads,
  callback bodies, cookies, signatures, nonces, or authorization headers
- train or fine-tune on customer content without a separately approved data
  contract
- bypass local plugin approval, entitlement, or governance contracts

## First Phase

The first implementation phase should stay narrow:

1. Runtime operations advisor
   - Inputs: runtime diagnostics, provider health, queue state, callback state,
     guard events, recent failed runs, and service audit evidence.
   - Output: operator summary, likely blocker, evidence links, and next
     investigation step.

2. Usage and commercial anomaly advisor
   - Inputs: usage meter events, billing snapshots, entitlement snapshots,
     budget pressure, quota denials, and reconciliation details.
   - Output: site/account risk summary, anomalous spend or usage signals, and
     operator follow-up recommendation.

3. Hosted routing and model recommendation advisor
   - Inputs: provider latency, provider failures, runtime outcomes, cost
     pressure, model capability metadata, and routing profile metadata.
   - Output: recommendation candidates for operator review, never automatic
     adoption.

The first landed implementation is an on-demand read API over existing Cloud
summaries. It does not persist advisor snapshots. It may call a configured
provider only through the Internal Ops Summarizer contract below.

The second landed implementation adds an Operations Analysis scope. It aggregates
existing Cloud data before model use:

- commercial coverage, recent usage totals, attention subscriptions, and expiry
  counts
- runtime queue, callback, guard, and run outcome metrics
- provider call count, error rate, fallback count, tokens, cost, latency, and
  top provider/model activity
- site-knowledge search volume, no-hit rate, failed searches, and current index
  coverage

This scope is still advisory. It does not auto-triage accounts, mutate router
profiles, modify WordPress, send customer messages, or create commercial state.

## Data Sources

The advisor may read from existing Cloud-owned evidence surfaces:

- runtime records and runtime diagnostics
- provider health and hosted stats
- usage meter events and usage rollups
- billing snapshots and reconciliation summaries
- entitlement snapshots and commercial decision traces
- service audit events
- plugin observability summaries
- media, vector, and site-knowledge observability summaries when present

Advisor inputs should be pre-aggregated or redacted before model use whenever
practical. Direct model access to production tables is not allowed. If natural
language analytics is added later, it must compile to bounded, reviewed queries
or read models with explicit allowlists.

## Output Shape

Advisor responses should be structured and evidence-backed:

```json
{
  "advisor_version": "internal-ai-advisor-v1",
  "scope": "runtime_operations",
  "status": "attention",
  "severity": "warning",
  "headline": "Provider failures increased in the last hour",
  "summary": "Recent failed runs cluster around one hosted provider.",
  "evidence": [
    {
      "kind": "runtime_diagnostics",
      "ref": "/internal/service/runtime/diagnostics/summary",
      "label": "runtime diagnostics summary"
    }
  ],
  "recommended_actions": [
    {
      "action": "inspect_provider_credentials_quota_and_health",
      "requires_operator": true
    }
  ],
  "confidence": "medium",
  "generated_at": "2026-06-04T00:00:00Z"
}
```

Rules:

- `recommended_actions` are advisory and require operator review.
- `evidence` must point to bounded internal or admin read surfaces, not raw
  secrets or payloads.
- `confidence` is a product hint, not an authorization decision.
- Advisor text must stay short enough for admin and support workflows.

## Internal Ops Summarizer

Internal Ops Summarizer is the only LLM-backed surface allowed in this contract.
It produces internal operator summaries and editable support reply drafts from
redacted advisor context.

Allowed:

- use advisor `scope`, `status`, `severity`, `headline`, `summary`,
  `confidence`, evidence refs, signal codes/counts, and recommended action ids
- produce `operator_summary`, `support_draft`, `operator_next_step`, and
  `safety_note`
- fall back to deterministic template text when no provider is configured or a
  provider call fails

Forbidden:

- generate articles, SEO content, product descriptions, blog drafts, marketing
  copy, or WordPress content
- send raw advisor `source`, raw runtime diagnostics, raw plugin payloads,
  prompts, completions, callback bodies, secrets, request/response bodies, or
  WordPress content to a model
- claim that an operator action has already been taken
- send drafts automatically to customers
- write WordPress or mutate Cloud commercial/router state

Initial API:

- `GET /internal/service/advisor/operations`
- `GET /internal/service/advisor/ops-summary`
- `GET /internal/service/advisor/ops-summary-preview`

The response must identify whether text came from a provider or deterministic
fallback using `generation.mode`. This mode is advisory evidence, not
authorization to execute anything.
Provider execution requires both:

- `MAGICK_CLOUD_INTERNAL_OPS_SUMMARIZER_PROVIDER_ALLOWLIST` includes the
  provider id
- the request explicitly passes that `provider_id`

Otherwise the endpoint must return deterministic fallback text. Each request
must write an internal `service_audit_events` row with generation mode,
provider/model ids, token counts, cost, and error code. Audit payloads must not
store prompts, model output text, customer content, or WordPress content.

The preview endpoint returns both deterministic baseline text and the provider
attempt result, plus a compact comparison (`ai_called`, `text_changed`,
`tokens_in`, `tokens_out`, `cost`, `value_check`). It exists only to help
operators decide whether LLM participation is worth enabling for this workflow.

## Storage

The first phase may store generated advisor snapshots in PostgreSQL read-model
tables or compute them on demand from existing summaries.

Allowed storage:

- advisor snapshot id
- scope and subject ids such as site, account, subscription, provider, model,
  or routing profile
- severity, status, headline, summary, structured evidence refs, recommended
  actions, confidence, generated timestamp, and expiry timestamp

Forbidden storage:

- raw prompts or completions containing customer content
- raw customer payloads, callback bodies, plugin payloads, or secrets
- durable copies of WordPress content
- unbounded model conversation history

Redis may be used only for short-lived cache, queue wake-up, cooldown, or
deduplication support. PostgreSQL remains the durable truth for advisor
snapshots and evidence references.

## API Surface

Initial API surfaces should be internal and bounded:

- `GET /internal/service/advisor/runtime`
- `GET /internal/service/advisor/commercial`
- `GET /internal/service/advisor/routing`
- `GET /internal/service/advisor/operations`
- `GET /internal/service/advisor/ops-summary`
- `GET /internal/service/advisor/ops-summary-preview`
- optional subject-scoped variants under existing admin site/account detail
  read APIs

These endpoints are internal/operator read surfaces. They must use existing
internal service or platform-admin authorization and must not be exposed as
customer runtime APIs.

Portal exposure is deferred. If a customer-facing portal summary is added
later, it must be site-scoped, redacted, and limited to operational explanation;
it must not expose internal operator guidance, cross-customer comparisons, or
provider credential details.

## Frontend Surface

Admin UI may show advisor cards or panels on existing bounded pages:

- `/admin`
- `/admin/sites/{site_id}`
- `/admin/accounts/{account_id}`
- `/admin/subscriptions/{subscription_id}`
- provider/runtime diagnostics pages

UI rules:

- show the recommendation, evidence, confidence, and next operator action
- make action buttons explicit operator commands when mutation already exists
  elsewhere
- do not add a new AI command center
- do not duplicate plugin settings, router editors, prompt editors, workflow
  editors, ability registries, or WordPress write controls

## Worker Shape

The first phase should use the existing Cloud worker pattern:

- periodic or event-triggered summary generation
- PostgreSQL-backed read models
- Redis only for wake-up, cooldown, dedupe, or short TTL cache
- OpenTelemetry spans for generation jobs and model/provider calls

Do not introduce Temporal, Celery, Kafka, RabbitMQ, NATS, Airflow, Kubernetes as
a first requirement, or a second scheduler/workflow truth.

## Acceptance Checks

An implementation is acceptable only if:

- local plugin truth remains unchanged
- Cloud outputs are advisory unless an existing operator mutation is explicitly
  invoked by a platform admin
- no raw customer content, secrets, prompts, completions, callback bodies, or
  plugin payloads are sent to advisor storage or surfaced in responses
- advisor endpoints are internal/operator scoped
- LLM prompts contain only redacted advisor context and never raw `source`
  payloads
- recommendations include evidence references
- no new control-plane surface is created
- no forbidden infrastructure is introduced
