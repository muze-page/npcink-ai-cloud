# Text Model Provider Integration Decision - 2026-07-11

## Status

Accepted for the current phase.

This document records the current decision for integrating multiple text-model
providers into Npcink AI Cloud. It summarizes the discussion that led to the
provider preset change and defines when the decision should be revisited.

## Executive Decision

Npcink AI Cloud will directly connect the expected 5-8 active text providers
through the existing provider-connection and hosted-runtime seams. Providers
that expose a sufficiently compatible OpenAI API will reuse the existing
`openai_compatible` adapter. A provider-specific adapter should be added only
when a real protocol or capability difference requires one.

LiteLLM remains a supported optional gateway connection, but it will not become
the mandatory path for OpenAI, DeepSeek, Kimi, Doubao, MiniMax, Xiaomi MiMo,
LongCat, Qwen, Hunyuan, or Zhipu GLM in the current phase. Existing direct
connections will not be migrated behind LiteLLM, and Cloud's canonical usage,
cost, health, and routing evidence will not be delegated to LiteLLM.

The immediate work stops at low-cost provider presets and compatibility tests.
It does not expand into a new gateway deployment, evaluation platform,
automatic routing policy, or broad provider enablement.

## Context

The expected text-model mix is not a single permanent supplier. Different
models may be selected later according to quality, latency, price, context
window, regional availability, and task characteristics. The likely operating
set contains 5-8 providers, selected from:

- OpenAI / ChatGPT models
- DeepSeek
- Kimi
- Doubao / Volcengine Ark
- MiniMax
- Xiaomi MiMo
- LongCat / Meituan
- Qwen / Alibaba Cloud Model Studio
- Hunyuan / Tencent
- Zhipu GLM

Most of these suppliers expose an OpenAI-compatible chat API. The project also
already has the following Cloud-owned runtime foundations:

- database-managed provider connections and encrypted credentials;
- namespaced provider/model identities;
- hosted routing profiles and fallback execution;
- `provider_call_records` for upstream call evidence;
- `usage_meter_events` for canonical usage metering;
- `credit_ledger_entries` for Cloud credit accounting;
- provider health, latency, error, and runtime diagnostics;
- read-only ability-to-model runtime projections.

The repository also already contains a bounded `litellm_gateway` adapter. It is
useful when an operator has an existing LiteLLM deployment, but its existence
does not require all providers to be routed through that gateway.

## Implemented Provider Presets

The admin provider-connection form now offers the following relevant presets.
A preset is an operator convenience, not proof that credentials, model access,
regional availability, pricing, or production readiness have been verified.

| Supplier | Adapter path | Current role |
| --- | --- | --- |
| OpenAI | `openai_compatible` | Existing general OpenAI-compatible entry |
| DeepSeek | `openai_compatible` | Direct text provider preset |
| Kimi | `openai_compatible` | Direct text provider preset |
| Doubao / Volcengine Ark | `openai_compatible` | Direct text provider preset |
| MiniMax | existing MiniMax support | Text and existing provider-specific capabilities |
| Xiaomi MiMo | `openai_compatible` | Direct text provider preset |
| LongCat / Meituan | `openai_compatible` | Direct text provider preset |
| Qwen / Alibaba Cloud Model Studio | `openai_compatible` | Direct text provider preset |
| Hunyuan / Tencent | `openai_compatible` | Direct text provider preset |
| Zhipu GLM | `openai_compatible` | Direct text provider preset |

The presets include default base URLs and example model allowlists to reduce
manual setup. Before enabling a connection, the operator must confirm the
supplier's current documentation and the models actually available to the
account, then use the existing connection test and one real text smoke run.

## Why LiteLLM Is Not the Default Path Now

### The current compatibility problem is already small

For the expected supplier set, the dominant protocol is OpenAI-compatible. A
shared adapter plus provider-specific connection data removes most integration
duplication without adding another deployed service.

### Mandatory LiteLLM would duplicate ownership

Cloud already owns hosted routing, fallback, usage evidence, health, and
commercial accounting. Putting every call behind LiteLLM would introduce a
second place for model aliases, retry and fallback policy, budgets, cost data,
and observability. Without a demonstrated gap, that increases configuration
drift and incident diagnosis time.

### LiteLLM cannot replace the Cloud usage ledger

LiteLLM may provide useful gateway telemetry and estimated cost metadata, but
Cloud must retain canonical records tied to its own `site_id`, `run_id`,
entitlements, billing periods, idempotency rules, credits, and audit evidence.
Gateway telemetry can be supplementary evidence; it is not a substitute for
`provider_call_records`, `usage_meter_events`, or `credit_ledger_entries`.

### The operational cost arrives before the benefit

A mandatory gateway adds deployment, upgrades, secrets, health checks,
timeouts, compatibility testing, and an extra network hop. With 5-8 mostly
compatible active providers, the expected short-term benefit does not yet
justify that permanent operational surface.

## What We Should Learn From LiteLLM

The project can adopt useful patterns without adopting LiteLLM as mandatory
infrastructure:

- normalize provider errors into stable retryable and non-retryable classes;
- keep model IDs namespaced and separate from operator-facing aliases;
- maintain explicit capability metadata instead of assuming all compatible
  endpoints support the same features;
- record latency, tokens, upstream request IDs, errors, and estimated cost at
  the provider-call boundary;
- make retries, timeouts, and fallback decisions visible in runtime evidence;
- isolate provider quirks in adapters rather than leaking them into abilities;
- test catalog and execution compatibility with contract fixtures;
- keep price metadata versioned and reconcile estimates against supplier bills.

These patterns should be added only when required by a real provider or
operational gap, using the current Cloud runtime stack.

## Activation Strategy

Provider availability should be expanded by evidence, not by the number of
presets in the UI.

### Initial operating set

Start with three actively configured providers:

1. OpenAI for a strong general baseline;
2. DeepSeek for price/performance and domestic availability evidence;
3. Qwen for a second domestic production path.

Keep the other presets disabled until a concrete model capability, customer
requirement, price advantage, or resilience need justifies activation. Kimi,
Doubao, MiniMax, Xiaomi MiMo, LongCat, Hunyuan, and Zhipu GLM remain cheap
options because their setup shape is already available.

### Per-provider acceptance

Before production enablement, require:

- credentials stored through the existing provider-connection path;
- current base URL and model allowlist confirmed against the supplier account;
- connection test passed;
- one real text-generation smoke passed;
- token, latency, error, and provider-call evidence recorded;
- timeout and rate-limit behavior understood;
- pricing metadata reviewed before cost-based routing or billing use;
- the provider left disabled if any required evidence is missing.

### Routing evolution

Do not implement automatic capability routing from assumptions. First collect
comparable real-call evidence for the active providers. Then define bounded
task profiles such as quality-first, economy, long-context, or low-latency
using Cloud's existing hosted routing seam. Any recommended routing profile
remains runtime enhancement; local WordPress governance, approval, and final
writes remain unchanged.

## Conditions for Reconsidering LiteLLM

The raw provider count alone is not a trigger. Reconsider a mandatory or more
central LiteLLM deployment only when measured evidence shows at least one of
these conditions:

- repeated provider protocol differences are causing substantial adapter code
  and maintenance duplication;
- several non-Cloud clients need the same virtual keys, quotas, aliases, and
  upstream credentials;
- provider onboarding or credential rotation is materially slower through the
  existing connection path;
- the current runtime cannot express a required cross-provider policy without
  duplicating substantial implementation;
- operations can demonstrate that a gateway reduces, rather than duplicates,
  incident diagnosis and cost reconciliation work;
- a controlled trial shows acceptable latency, failure isolation, telemetry
  reconciliation, and rollback behavior.

Before centralizing on LiteLLM, run it as a single optional provider connection
for a limited traffic slice. Compare direct and gateway paths for latency,
error rate, token accounting, cost reconciliation, model-feature fidelity, and
operational effort. Do not migrate all providers until the trial has a clear
owner, success thresholds, and a tested direct-connection rollback.

## Benefits and Costs of the Current Decision

Expected benefits:

- fast access to a broad supplier set with small code changes;
- one familiar configuration and testing path for operators;
- no new service or network hop for normal provider calls;
- Cloud usage, billing, health, and routing evidence stays coherent;
- providers can be activated gradually without committing to all of them;
- future provider-specific adapters remain possible where compatibility ends.

Accepted costs and limitations:

- some supplier quirks may still require targeted adapter logic;
- OpenAI compatibility does not guarantee identical streaming, tool calling,
  reasoning fields, token usage, or error semantics;
- model names, URLs, availability, and prices can drift and require operator
  review;
- Cloud remains responsible for its own catalog, telemetry, reconciliation,
  and runtime tests.

For the current phase, this is a favorable trade: most of the option value is
captured by presets and a shared adapter, while the complexity of a mandatory
gateway is deferred until evidence can justify it.

## Boundary and Non-Goals

This decision stays inside the hosted runtime enhancement layer.

Cloud may own provider connections, adapters, execution, hosted routing,
provider-call evidence, usage metering, cost evidence, health, and diagnostics.
It must not become a second WordPress control plane, ability registry, workflow
registry, prompt/preset truth, or final write owner.

This phase explicitly does not add:

- a new LiteLLM service or mandatory gateway;
- a second model registry or routing control plane;
- automatic enablement of every preset;
- automatic model evaluation or self-modifying routing;
- a replacement usage or credit ledger;
- a new database schema or public runtime API;
- any WordPress write, approval, or preflight behavior.

## Next Review Point

Stop implementation after the provider preset change and this decision record.
The next useful action is operational validation when real supplier credentials
are available: configure the initial operating set, run connection tests and
one real text smoke per provider, then review comparable evidence before adding
routing policy or infrastructure.

Review this decision after either:

- three providers have accumulated enough representative production evidence
  to expose a real routing or compatibility gap; or
- a new client or provider requirement meets one of the LiteLLM reconsideration
  conditions above.

## Related Documents

- [Hosted Model Runtime V1](legacy-contracts/magick-ai-root/magick-ai/docs/contracts/hosted-model-runtime-v1.md)
- [Cloud Technical Stack Guardrails V1](legacy-contracts/magick-ai-root/ai/docs/contracts/cloud-technical-stack-guardrails-v1.md)
- [AI Provider Env Config Retirement - 2026-06-26](ai-provider-env-config-retirement-2026-06-26.md)
