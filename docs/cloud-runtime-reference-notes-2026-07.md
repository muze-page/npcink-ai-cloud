# Cloud Runtime Reference Notes - 2026-07

Status: reference notes for next-stage planning.

Question: for hosted runtime, admin/detail surfaces, usage evidence,
observability, and runtime diagnostics, do mature cloud products already solve
similar operator problems we can learn from?

Short answer: yes. Npcink AI Cloud should learn the clarity patterns from
runtime observability, error-debugging, usage, and billing systems. It should
not copy their full control planes, alerting products, provider marketplaces,
workflow engines, or customer-facing commercial front-office.

## Current Cloud Baseline

Npcink AI Cloud already owns:

- hosted runtime execution and provider adapters;
- usage, entitlement, billing snapshot, and audit evidence;
- health, runtime diagnostics, provider health, and service detail;
- Site Knowledge runtime/detail and Cloud-owned indexing execution;
- artifact storage and runtime run/result detail;
- read-only Agent and Workflow metadata projection;
- metadata-only Agent feedback and plugin observability rollups;
- bounded admin and portal detail surfaces.

Cloud must continue to avoid:

- WordPress proposal, approval, preflight, audit, or final write truth;
- a second local ability registry or workflow registry;
- prompt, router, preset, MCP, OpenClaw, or Agent Gateway control-plane truth;
- WordPress writes or content publishing;
- a durable orchestration product beyond the current worker/Redis/DB runtime
  seam;
- generic customer-facing admin suites that duplicate local plugin settings.

## Reference Sources

| Reference | Similar capability | Useful lesson | Boundary note |
| --- | --- | --- | --- |
| [OpenTelemetry](https://opentelemetry.io/docs/) | Vendor-neutral traces, metrics, and logs. | Shared trace/context vocabulary helps correlate runtime, provider, worker, and addon detail without inventing product-specific debug formats everywhere. | Borrow signal discipline, not a new observability platform or vendor lock-in. |
| [Vercel Observability](https://vercel.com/docs/observability) and [Runtime Logs](https://vercel.com/docs/logs/runtime) | Project-level runtime logs, filters, and performance views. | Runtime detail should start from deployment/project/run context, then let operators filter into one failing request. | Do not build a generic logs product, customer support console, or broad app-performance suite. |
| [Cloudflare Workers Observability](https://developers.cloudflare.com/workers/observability/) | Request traces and worker runtime visibility. | End-to-end request path visibility is useful when it stays tied to one runtime execution and connected services. | Do not copy edge platform controls, worker deployment ownership, or binding configuration UI. |
| [Sentry Issue Details](https://docs.sentry.io/product/issues/issue-details/) | Error event context, breadcrumbs, and timeline-style debugging. | For a failed run, the operator needs a compact event timeline and cause hints, not raw payload dumps. | Do not store prompts, generated content, secrets, or raw customer payloads as debugging convenience. |
| [AWS CloudWatch](https://aws.amazon.com/documentation-overview/cloudwatch/) and [Datadog Monitors](https://docs.datadoghq.com/monitors/) | Metrics, logs, dashboards, and alerting. | Service health summaries should distinguish metrics, logs, traces, monitors, and attention items. | Do not add a broad alerting suite, infrastructure monitoring product, or on-call operations console in this phase. |
| [Stripe usage-based billing](https://docs.stripe.com/billing/usage-based) and [OpenAI rate limits](https://developers.openai.com/api/docs/guides/rate-limits) | Usage, limits, metering, and customer-facing constraints. | Usage/limit explanations should be visible, predictable, and separated from governance decisions. | Cloud can own usage and entitlement evidence; it must not become WordPress governance truth or local write policy. |

## What To Borrow

Borrow these patterns because they make runtime/detail surfaces easier to trust:

- one run detail page shape: status, timeline, model/provider, execution
  contract, storage mode, usage, entitlement decision, artifacts, and error
  cause;
- correlation identifiers across addon, runtime, worker, provider call, and
  callback delivery;
- separate tabs or sections for metrics, logs, traces, usage, and audit
  evidence rather than one raw dump;
- low-cardinality summary cards first, then drill-down into one run, site,
  provider, account, or time window;
- explicit retention and data-classification labels for stored run evidence;
- cause categories that separate auth, entitlement, provider, timeout,
  contract mismatch, queue pressure, callback, and policy denial;
- read-only quality dashboards that show rates and trends without adding
  mutation controls;
- clear operator links from Cloud detail back to the local owner when the next
  action is WordPress approval, Toolbox review, Adapter execution, or Addon
  reconnection.

## What Not To Borrow

Do not import these product patterns into Npcink AI Cloud:

- generic log ingestion, arbitrary search over raw customer payloads, or
  permanent prompt/result retention;
- customer-facing alert policies, on-call routing, incident management, or
  infrastructure monitoring suites;
- a marketplace of models, providers, workflows, skills, MCP servers, or
  OpenClaw projections;
- prompt/preset/router editing as Cloud truth;
- workflow builders, stage engines, durable orchestration products, scheduler
  truth, or second workflow engines;
- WordPress proposal approval, publish, media import, SEO mutation, taxonomy
  write, or final execution authority;
- billing front-office expansion beyond the current bounded service-plane
  policy and evidence surfaces.

## Candidate Improvements

### P1 - Preserve Runtime/Detail Shape

Keep Cloud focused on:

- hosted execution;
- provider/runtime health;
- usage and entitlement evidence;
- bounded admin/portal detail;
- observability and quality rollups;
- Site Knowledge runtime/detail.

Do not reopen retired task packs, broad model operations consoles, prompt/preset
advisor products, or workflow registries as a side effect of improving
diagnostics.

### P1 - Improve Run Detail Trust Cues

Future run/detail work should keep these fields visible and stable:

- runtime owner: Cloud runtime, worker, provider adapter, Site Knowledge, or
  artifact service;
- local owner: Toolbox, Addon, Adapter, Core, or Abilities Toolkit;
- execution contract: ability name, contract version, execution pattern,
  timeout, retry, callback mode, data classification, and storage mode;
- posture: suggestion-only, runtime detail, proposal-input-ready, or blocked;
- next action owner: Cloud operator, local WordPress administrator, Core
  reviewer, Toolbox operator, Addon reconnect, or no action.

### P1 - Clarify Observability Boundaries

Observability and Agent feedback should stay metadata-only by default:

- show rates, counts, labels, source runtime, local surface, reason codes, and
  quality signals;
- avoid prompts, article body content, generated content, provider raw payloads,
  secrets, cookies, nonces, and authorization headers;
- keep dashboards read-only unless a separate service-plane decision defines a
  bounded operator action;
- use trends to decide what to investigate, not to mutate prompts, routers,
  approvals, or WordPress objects.

### P2 - Borrow Timeline Shape For Failures

For failed or blocked runtime work, a compact timeline would be more useful
than a larger dashboard:

- request accepted;
- execution contract checked;
- entitlement/commercial gate decision;
- queue/worker transition;
- provider call or Site Knowledge action;
- artifact/result stored or skipped by storage mode;
- callback delivered, retryable, or failed closed;
- local next action owner.

This can be documented first as a UI acceptance checklist before adding or
changing code.

### P2 - Keep Usage Explanation Separate From Governance

Usage and limit views should explain consumption without implying write
permission:

- usage meter event;
- entitlement snapshot;
- budget soft limit or downgrade policy;
- quota-exhausted state;
- plan/package presentation;
- link to local governance owner for WordPress write decisions.

## Decision Gate For New Cloud Work

Before adding a new Cloud runtime/detail/admin surface, answer:

1. Is this hosted runtime, service evidence, or read-only detail?
2. Which existing runtime, worker, DB truth, or admin/portal seam owns it?
3. Does it need a new endpoint, schema, or infrastructure component?
4. Does it imply Cloud owns WordPress approval, prompt/router/preset truth,
   ability/workflow registry truth, or final writes?
5. Is the data stored under an explicit retention and data-classification
   posture?
6. Can the local plugin path still fail closed without Cloud becoming the only
   control plane?

If the answer points to local governance, broad orchestration, prompt/router
control, a customer-facing operations console, or WordPress writes, the work is
outside current Cloud scope.

## Suggested Next Artifact

The next implementation planning artifact should be a runtime-detail UI
acceptance checklist for existing surfaces only. It should verify that each
runtime/detail view shows:

- run identity and correlation ids;
- contract and storage posture;
- usage/entitlement evidence;
- provider or worker status;
- artifact/result retention state;
- failure cause category;
- local next-action owner;
- no prompt/router/preset mutation controls;
- no WordPress proposal, approval, or write controls;
- no new workflow registry or scheduler truth.
