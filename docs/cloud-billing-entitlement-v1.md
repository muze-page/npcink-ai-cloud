# Cloud Billing Entitlement v1

Status: active
Date: 2026-05-27

## Scope

This specification freezes only the Cloud billing entitlement contract. It does
not define checkout, invoices, dunning, self-serve payment, WordPress writes,
router ownership, profile ownership, prompt ownership, or approval ownership.

Cloud may expose billing and entitlement detail for hosted service use. The
local plugin remains the product control plane.

## 1. Paid Objects

Billing entitlement attaches to exactly these paid object shapes:

| Object | Meaning | Boundary |
|--------|---------|----------|
| `site` | One provisioned Cloud site that maps to one connected WordPress install. | Cloud may enforce hosted runtime entitlement for the site; it must not write WordPress. |
| `agency` | A customer/operator account that covers multiple sites or stores. | Cloud may aggregate entitlement coverage and usage; it must not become a second product control plane. |
| `woo_store` | A WooCommerce store attached to a connected site. | Cloud may meter Woo task pack usage and report entitlement; Woo product/catalog truth and writes stay local. |

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

`woo_store` may include a `site_id` plus a stable store reference, but the store
reference is never permission to mutate WooCommerce from Cloud.

## 2. Packages

The public package names are frozen:

| Package | Internal tier compatibility | Purpose |
|---------|-----------------------------|---------|
| `Free` | `starter` | Conservative single-site baseline. |
| `Pro` | `pro` | Normal hosted runtime and workflow usage. |
| `Agency` | `agency` | Multi-site or sustained higher-volume usage. |

Rules:

- `Free / Pro / Agency` are the only public package names for this contract.
- Existing internal tier ids may remain `starter / pro / agency`.
- Legacy presentation aliases such as `Basic` and `Bulk` must not be introduced
  into new entitlement API fields.
- Plan and plan-version records remain the package execution truth inside Cloud.

## 3. Entitlement Fields

An entitlement snapshot must express these fields only for the v1 contract:

```json
{
  "package": "Pro",
  "package_tier": "pro",
  "task_packs": {
    "allowed": [
      "woocommerce-growth",
      "geo-visibility",
      "managed-model-routing"
    ]
  },
  "usage_limits": {
    "period": "month",
    "max_runs": 10000,
    "max_tokens": 2000000,
    "max_cost_usd": 99.0,
    "max_sites": 5
  },
  "analytics_retention": {
    "days": 90
  },
  "hosted_runtime_quota": {
    "max_active_runs": 2,
    "max_batch_items": 10,
    "execution_tiers": ["cloud"]
  }
}
```

Field rules:

- `task_packs.allowed` lists Cloud task pack ids available to the paid object.
- `usage_limits` is the customer-visible limit shape for the active billing
  period.
- `analytics_retention.days` controls Cloud analytics/log summary visibility; it
  does not create indefinite retention.
- `hosted_runtime_quota` controls Cloud runtime headroom only.
- Entitlement may restrict hosted execution, but it must not expand local
  plugin contracts, WordPress write permissions, approvals, router truth,
  prompt truth, or profile truth.

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
      "task_packs": {
        "allowed": ["woocommerce-growth", "geo-visibility"]
      },
      "usage_limits": {
        "period": "month",
        "max_runs": 10000,
        "max_tokens": 2000000,
        "max_cost_usd": 99.0,
        "max_sites": 5
      },
      "analytics_retention": {
        "days": 90
      },
      "hosted_runtime_quota": {
        "max_active_runs": 2,
        "max_batch_items": 10,
        "execution_tiers": ["cloud"]
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
