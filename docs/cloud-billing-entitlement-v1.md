# Cloud Billing Entitlement v1

Status: active
Date: 2026-05-27

## Scope

This specification freezes only the Cloud billing entitlement contract. It does
not define checkout, invoices, dunning, self-serve payment, WordPress writes,
router ownership, profile ownership, prompt ownership, or approval ownership.
Payment order/refund event handling is separately scoped by
`docs/cloud-payment-entitlement-v1.md`.

Cloud may expose billing and entitlement detail for hosted service use. The
local plugin remains the product control plane.

## 1. Paid Objects

The current public entitlement query attaches to one paid object shape:

| Object | Meaning | Boundary |
|--------|---------|----------|
| `site` | One provisioned Cloud site that maps to one connected WordPress install. | Cloud may enforce hosted runtime entitlement for the site; it must not write WordPress. |

Every entitlement response must include the resolved paid object:

```json
{
  "paid_object": {
    "type": "site",
    "id": "site_123",
    "account_id": "acct_123"
  }
}
```

Account or agency-level commercial coverage may still be inspected by internal
operator surfaces, but it is not a public entitlement object in this v1 API.
Any future store-level or agency-level public entitlement object requires a new
contract update before use.

## 2. Packages

The public package names are frozen:

| Package | Internal tier id | Purpose |
|---------|-----------------------------|---------|
| `Free` | `free` | Conservative single-site baseline. |
| `Pro` | `pro` | Normal hosted runtime and workflow usage. |
| `Agency` | `agency` | Multi-site or sustained higher-volume usage. |

Rules:

- `Free / Pro / Agency` are the only public package names for this contract.
- Internal tier ids are `free / pro / agency`.
- Non-approved legacy package aliases must not be introduced
  into new entitlement API fields.
- Plan and plan-version records remain the package execution truth inside Cloud.

## 3. Entitlement Fields

An entitlement snapshot must express these fields only for the v1 contract:

```json
{
  "package": "Pro",
  "package_tier": "pro",
  "usage_limits": {
    "period": "month",
    "max_ai_credits": 0,
    "max_sites": 0
  },
  "analytics_retention": {
    "days": 90
  },
  "hosted_runtime_quota": {
    "max_active_runs": 0,
    "max_batch_items": 0,
    "execution_tiers": ["cloud"]
  },
  "pro_cloud_runtime": {
    "contract_version": "pro-cloud-runtime-entitlement-v1",
    "feature_id": "nightly_site_inspection",
    "execution_pattern": "whole_run_offload",
    "meter_key": "ai_credits",
    "limit_enforced": false,
    "max_nightly_inspection_runs_per_period": 0,
    "used_nightly_inspection_runs": 7,
    "remaining_nightly_inspection_runs": 0,
    "quota_exhausted": false,
    "max_batch_items": 25,
    "result_retention_days": 21,
    "payload_modes": ["metadata_only", "excerpt"],
    "cloud_role": "runtime_detail",
    "local_truth": {
      "schedule_owner": "wordpress_wp_cron_or_local_runtime",
      "runtime_owner": "npcink-local-automation-runtime",
      "final_write_path": "core_proposal_required",
      "direct_wordpress_write": false
    },
    "contract_reuse": {
      "cloud_role": "runtime_detail",
      "toolbox_role": "product_surface",
      "core_role": "proposal_handoff",
      "adapter_role": "execution_profiles",
      "toolkit_role": "ability_contracts",
      "addon_role": "signed_transport",
      "adds_registry": false,
      "adds_scheduler_truth": false,
      "adds_approval_store": false,
      "adds_queue": false,
      "adds_write_executor": false
    }
  }
}
```

Field rules:

- `usage_limits` is the customer-visible limit shape for the active billing
  period. During internal development before release, `0` means the package
  does not block on that quota while usage and audit evidence remain active.
- `analytics_retention.days` controls Cloud analytics/log summary visibility; it
  does not create indefinite retention.
- `hosted_runtime_quota` controls Cloud runtime headroom only.
- `pro_cloud_runtime` is a read-only detail surface for Toolbox Pro controls. It
  reports Nightly Site Inspection quota, usage, remaining count, batch item cap,
  result-retention guidance, and payload modes. It does not create a Cloud
  scheduler, local write permission, or second approval truth.
- `pro_cloud_runtime.contract_reuse` is a read-only boundary projection. It
  states that Cloud owns runtime/detail, Toolbox owns product surface, Core owns
  proposal handoff, Adapter owns execution profiles, Toolkit owns ability
  contracts, and Cloud Addon owns signed transport. It must keep
  `adds_registry`, `adds_scheduler_truth`, `adds_approval_store`, `adds_queue`,
  and `adds_write_executor` false.
- Entitlement may restrict hosted execution, but it must not expand local
  plugin contracts, WordPress write permissions, approvals, router truth,
  prompt truth, or profile truth.

## 3.1 Model-Agnostic Hosted Runtime Governance

Hosted runtime quota and metering apply to every Cloud-managed model capability,
not only the current free GPT-5.5 text profile. Cloud must preserve these
governance dimensions on accepted runs, provider calls, usage meter events, and
commercial decision events:

- `ability_family`
- `execution_kind`
- `execution_tier`
- `data_classification`
- `profile_id`
- provider/model/instance identifiers when an upstream provider is called

Current managed capability examples include:

| Capability | Typical profile | Ability family | Execution kind | Required governance |
|------------|-----------------|----------------|----------------|---------------------|
| Hosted text generation | `text.free-gpt55` or later hosted text profiles | `text`, `workflow`, `automation`, `mcp`, or `openclaw` | `text` or caller contract value | run, provider call, token, and cost meters |
| AI image generation | `grok-imagine-image-quality` or later hosted image profiles | `vision` | `image_generation` | run, provider call, cost meters, result storage mode, and local write boundary |
| Image/reference media search | `image-source.managed` | `knowledge` | `image_source` | run, provider call, and cost meters |
| Web search/evidence | `web-search.managed` | `knowledge` | `web_search` | run, provider call, and cost meters |
| Site knowledge/vector search | `site-knowledge.managed` | `knowledge` | `knowledge` or `embedding` | run meters plus provider call/token/cost meters for managed embedding providers |
| Media derivative processing | `media_derivative.worker` | `vision` | `media_derivative` | run meters and queue/concurrency controls |

New hosted text, image, embedding/vector, search, audio, or multimodal model
adapters must enter through the same runtime authorization path. They must not
create a model-specific bypass around entitlement, request guard, idempotency,
quota, concurrency, provider-call telemetry, usage meter events, storage mode,
or WordPress write boundaries.

Internal operators may inspect this posture through:

```http
GET /internal/service/runtime/diagnostics/runtime-telemetry
```

This diagnostic endpoint is internal-only and read-only. It may summarize
ability-family, execution-kind, profile, provider, model, token, cost, latency,
error, and metering-coverage signals, but it must not return prompts, generated
content, raw runtime inputs/results, provider secrets, WordPress credentials,
or any local approval/write controls.

The former `hosted-model-governance` compatibility aliases are retired. Current
surfaces must use the runtime telemetry name because the evidence covers all
hosted runtime execution families, not a standalone model governance product
area.

## 4. Cloud API Query

The local plugin queries entitlement through a read-only Cloud API:

```http
GET /v1/entitlements/current?object_type=site&object_id=site_123
```

Authentication:

- Uses the existing site-scoped Cloud API key / HMAC request authentication.
- `GET` requests do not require a runtime nonce unless the general Cloud auth
  layer requires one for all signed requests.
- Required scope: `entitlement:read`.

Response:

```json
{
  "data": {
    "contract_version": "cloud-billing-entitlement-v1",
    "paid_object": {
      "type": "site",
      "id": "site_123",
      "account_id": "acct_123"
    },
    "package": "Pro",
    "package_tier": "pro",
    "status": "active",
    "period": {
      "start_at": "2026-05-01T00:00:00Z",
      "end_at": "2026-06-01T00:00:00Z"
    },
    "entitlement": {
      "usage_limits": {
        "period": "month",
        "max_ai_credits": 0,
        "max_sites": 0
      },
      "analytics_retention": {
        "days": 90
      },
      "hosted_runtime_quota": {
        "max_active_runs": 0,
        "max_batch_items": 25,
        "execution_tiers": ["cloud"]
      },
      "pro_cloud_runtime": {
        "contract_version": "pro-cloud-runtime-entitlement-v1",
        "feature_id": "nightly_site_inspection",
        "execution_pattern": "whole_run_offload",
        "meter_key": "ai_credits",
        "limit_enforced": false,
        "max_nightly_inspection_runs_per_period": 0,
        "used_nightly_inspection_runs": 0,
        "remaining_nightly_inspection_runs": 0,
        "quota_exhausted": false,
        "max_batch_items": 25,
        "result_retention_days": 14,
        "payload_modes": ["metadata_only", "excerpt"],
        "cloud_role": "runtime_detail",
        "local_truth": {
          "schedule_owner": "wordpress_wp_cron_or_local_runtime",
          "runtime_owner": "npcink-local-automation-runtime",
          "final_write_path": "core_proposal_required",
          "direct_wordpress_write": false
        },
        "contract_reuse": {
          "cloud_role": "runtime_detail",
          "toolbox_role": "product_surface",
          "core_role": "proposal_handoff",
          "adapter_role": "execution_profiles",
          "toolkit_role": "ability_contracts",
          "addon_role": "signed_transport",
          "adds_registry": false,
          "adds_scheduler_truth": false,
          "adds_approval_store": false,
          "adds_queue": false,
          "adds_write_executor": false
        }
      }
    }
  }
}
```

API rules:

- The API is read-only.
- The API may return `inactive`, `suspended`, or `uncovered` status, but it must
  not auto-create sites, subscriptions, stores, keys, plans, or approvals.
- The plugin may cache the response for display and runtime gating hints, but
  final local governance still comes from the local plugin contracts.

## 5. Forbidden Items

Cloud must not:

- write WordPress content, settings, WooCommerce products, WooCommerce orders,
  or WooCommerce store configuration
- own router truth, adopted routing profiles, local profile enablement, prompt
  truth, preset truth, or local workflow truth
- become the approval truth for content changes, WooCommerce writes, profile
  adoption, prompt adoption, or WordPress object mutation
- expose entitlement as permission to bypass local plugin approval
- turn task packs into a workflow engine, product control plane, router editor,
  prompt editor, or WooCommerce editor
- treat Redis, queues, callbacks, analytics projections, or billing snapshots as
  WordPress truth

The allowed Cloud role is billing and entitlement detail plus hosted runtime
quota enforcement.
