# Internal AI Advisor v1

Status: active
Date: 2026-06-04

## Scope

Internal AI Advisor defines how Npcink AI Cloud may use AI for our own cloud
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

4. Site diagnostics advisor
   - Inputs: site monitoring overview, plugin observability attention items,
     media/vector/runtime/quota/key health, and recent activity summaries.
   - Output: up to three prioritized diagnostic items with evidence summary,
     likely cause, one next step, evidence window, generated timestamp, and
     lightweight workflow status for operator review.
   - Non-goal: automatic WordPress repair, plugin setting mutation, or Cloud
     creation of local Core proposals.

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
- site monitoring overview summaries and action-required items

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
- `GET /internal/service/advisor/site-diagnostics`
- `GET /internal/service/advisor/ops-summary`
- `GET /internal/service/advisor/ops-summary-preview`
- `POST /internal/service/advisor/ops-summary-review`
- `GET /internal/service/advisor/ops-summary-history`
- `GET /internal/service/advisor/ops-summary-value`
- `GET /portal/v1/sites/{site_id}/diagnostic-advisor`
- `GET /portal/v1/sites/{site_id}/ai-insights/history`
- `POST /portal/v1/sites/{site_id}/ai-insights/analyze`

The Portal endpoints are customer-facing read/detail surfaces over the same
advisor contract. They are not provider configuration endpoints. Site administrators
cannot pass `provider_id`, `model_id`, token budgets, prices, prompt templates,
or cache keys. The service resolves an allowlisted provider internally and
falls back to deterministic analysis when no provider is configured.

Portal AI analysis is manual-trigger only:

- page load may read cached history
- `POST /ai-insights/analyze` is the only action that may call a provider
- default cache TTL is 30 minutes
- `force_refresh=true` is explicit and still does not expose provider details

Portal responses may expose:

- headline, operator summary, next step, status, severity, generated time
- Magick AI disclosure, visible label, and review status
- cache hit/fresh-until state without the cache key
- safety flags showing no WordPress write, no raw prompt persistence, and no
  article generation

Portal responses must not expose:

- upstream provider or model id
- token counts, cost, internal price mapping, or request cost
- cache key, raw prompt, raw model payload, source context, secrets, callback
  bodies, or WordPress content
- admin review mutation controls

The response must identify whether text came from a provider or deterministic
fallback using `generation.mode`. This mode is advisory evidence, not
authorization to execute anything.
Admin and Portal responses may expose `agent_metadata_projection` so UI surfaces
can render the Advisor's static handoff boundary from the Cloud read-only
metadata projection instead of page-local constants. This field is display/detail
metadata only; it does not approve actions or create a workflow truth.
Every text-bearing summary response must also include `ai_disclosure` as
defined by [AI Generated Content Disclosure v1](ai-generated-content-disclosure-v1.md).
For `llm` and `llm_cached`, the output must be visibly labeled as Magick AI
generated and must remain in `needs_review` status until a human confirmation
event exists.
Human confirmation is scoped to the cached analysis entry and updates only
`ai_disclosure.review_status`; it does not approve WordPress writes, send drafts
to customers, or mutate Cloud commercial/router state.
History listing is read-only and sourced from stored summary cache projections.
It may expose headline, operator summary excerpt, generation metadata, internal
cost, cache freshness, and AI disclosure review state. It must not expose raw
prompts, raw provider payloads, full `source_context`, callback bodies, secrets,
or WordPress content.
Provider execution requires both:

- `NPCINK_CLOUD_INTERNAL_OPS_SUMMARIZER_PROVIDER_ALLOWLIST` includes the
  provider id
- the request explicitly passes that `provider_id`

When provider execution is enabled, the default model id is `gpt-5.5`. Callers
may pass a narrower `model_id` only for an explicit internal test or migration
case.

Otherwise the endpoint must return deterministic fallback text. Each request
must write an internal `service_audit_events` row with generation mode,
provider/model ids, token counts, cost, and error code. Audit payloads must not
store prompts, model output text, customer content, or WordPress content.

The preview endpoint returns both deterministic baseline text and the provider
attempt result, plus a compact comparison (`ai_used`, `ai_called`, `cache_hit`,
`cache_status`, `text_changed`, `tokens_in`, `tokens_out`, `cost`,
`request_cost`, `value_check`). `ai_called` means the current request reached the
provider. `ai_used` also covers cached AI output. It exists only to help
operators decide whether LLM participation is worth enabling for this workflow.

Operations preview also includes redacted drilldown evidence for failed runs,
run sites, ability families, provider/model breakdown, knowledge search
breakdown, and usage totals. These fields are aggregate or identifier-only
diagnostic evidence. They must not include raw request input, result payloads,
callback bodies, secrets, prompts, or WordPress content.

## AI Value Metrics

`GET /internal/service/advisor/ops-summary-value` is an internal-only evaluation
surface for deciding whether AI analysis is worth continued spend. It reads
advisor audit events and cached summary disclosure state. It does not call a
provider and does not expose data to site administrators.

Allowed metrics:

- analysis request count
- live AI call count
- cached AI reuse count and estimated cache savings
- deterministic fallback, provider error, and blocked counts
- token and provider cost totals for internal operators
- review status counts: `needs_review`, `human_confirmed`, `edited_after_ai`
- top provider/model internal cost breakdown

`human_confirmed` is the first implementation's "adopted/useful" proxy.
`edited_after_ai` means AI helped but the output required human changes. A later
workflow may replace this proxy with stronger evidence such as linked tickets,
operator actions, or customer retention impact.

This value surface must remain internal. Customer-facing Portal pages must not
show provider prices, cost mapping, token usage, cache keys, or upstream model
identity.

## AI Analysis Cache

AI operations analysis should not call the provider on every page refresh.
`/advisor/ops-summary` and `/advisor/ops-summary-preview` use a 30 minute
default cache (`cache_ttl_seconds=1800`). Operators may pass
`force_refresh=true` to bypass the cache and refresh the cached analysis, or
`cache_ttl_seconds=0` to disable caching for a request.

The cache key covers summarizer version, scope, site id, draft kind, window
parameters, provider id, and model id. Cache hits return generation mode
`llm_cached`, `cache_hit=true`, and `request_cost=0.0`. The original provider
cost remains in `cost` so internal operators can compare saved spend.

Cache storage must use the service read-model boundary. It may store the
redacted AI summary and redacted drilldown evidence, but it must not store raw
prompts, raw provider payloads, secrets, callback bodies, or WordPress content.
The cache is an internal operator efficiency mechanism, not a WordPress-side
state machine and not a second control plane.

## Provider Pricing

OpenAI-compatible providers should estimate upstream cost from the provider
usage payload whenever possible. DeepSeek uses cache-aware input pricing, so the
adapter must prefer `prompt_cache_hit_tokens` and `prompt_cache_miss_tokens`
when they are present. If those fields are missing, the conservative fallback is
to price all input tokens as cache-miss input.

DeepSeek pricing snapshot:

- Source: `https://api-docs.deepseek.com/quick_start/pricing`
- Checked: 2026-06-04
- Unit: USD per 1M tokens
- `deepseek-v4-flash`: input cache hit `$0.0028`, input cache miss `$0.14`,
  output `$0.28`
- `deepseek-v4-pro`: input cache hit `$0.003625`, input cache miss `$0.435`,
  output `$0.87`
- Compatibility names `deepseek-chat` and `deepseek-reasoner` currently map to
  `deepseek-v4-flash`, but the provider page says they will be deprecated on
  2026-07-24 15:59 UTC.

Recommendation: keep this mapping as a narrow adapter fallback for internal cost
visibility, but move provider pricing into catalog metadata or an internal
pricing table before external billing decisions depend on it. End customers
should buy the AI analysis service capability, not see upstream token API price
tables in the product surface.

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

Portal exposure is limited to site-scoped, redacted operational explanation.
`/portal/v1/sites/{site_id}/diagnostic-advisor` may show the current site's top
diagnostic items, likely causes, next steps, evidence window, generation time,
and lightweight workflow status (`new`, `acknowledged`, `muted`, `resolved`).
Status is review context only; it must not grant Cloud a WordPress write path or
repair authority. Portal diagnostics must not expose internal operator guidance,
cross-customer comparisons, provider credential details, raw plugin payloads, or
repair controls.

## Frontend Surface

Admin UI may show advisor cards or panels on existing bounded pages:

- `/admin`
- `/admin/sites/{site_id}`
- `/admin/accounts/{account_id}`
- `/admin/subscriptions/{subscription_id}`
- provider/runtime diagnostics pages

UI rules:

- show the recommendation, evidence, confidence, and next operator action
- keep site diagnostics to three default-visible items
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
