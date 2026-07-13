# AI Credit Charge Contract v1

Status: active

This contract defines how new AI abilities or cloud features become billable in Npcink AI Cloud.

Cloud remains the billing and runtime detail owner. This contract does not move ability, workflow, approval, or WordPress write truth out of the local/plugin side.

## Source Of Truth

The code truth is `app/domain/commercial/credits.py`.

Every billable AI capability must be represented by:

- `AI_CREDIT_COMPONENT_POLICY_REGISTRY` for ledger components.
- `AI_CREDIT_CAPABILITY_POLICY_REGISTRY` for runtime capability classification.
- `AI_CREDIT_FEATURE_CHARGE_RULES` for product feature to capability/component mapping.

Do not add a second billing registry in route handlers, workers, providers, or frontend code.

## Component Fields

Each ledger component must declare:

- `source_type`: stable ledger source type.
- `charge_mode`: `consume` or `meter_only`.
- `unit`: quantity unit.
- `rate`: AI credit rate.
- `minimum_charge`: minimum charge floor for this component.
- `idempotency_scope`: idempotency boundary for ledger writes.
- `budget_key`: commercial budget key, currently `ai_credits`.

Ledger consume writes must use `record_credit_ledger_component()` or the repository `record_credit_ledger_entry()` with a deterministic idempotency key.

## Capability Fields

Each runtime capability policy must declare:

- `capability_key`: stable capability classifier.
- `charge_mode`: runtime charge strategy.
- `request_base_credits`: preflight estimate used by budget gates.
- `ledger_components`: allowed ledger components for realized usage.
- `idempotency_scope`: idempotency boundary for the request.
- `budget_key`: commercial budget key, currently `ai_credits`.

## Rules For New AI Features

1. Add or reuse a component policy before writing ledger entries.
2. Add or reuse a capability policy before authorizing runtime usage.
3. Add or reuse a feature charge rule before exposing a product feature.
4. Include focused tests covering estimate, ledger entry, feature rule coverage, and idempotency.
5. Do not charge from frontend input. The server owns amount, rate, and ledger delta.
6. Grants, refunds, and operator adjustments must stay separate from consume components.

## Product Budget Rule

AI credits are the only customer-purchasable consumption budget. Runtime runs,
tokens, provider cost, batch size, and provider-specific calls may still be
recorded as usage evidence, diagnostics, ledger components, or internal
guardrails, but they must not be exposed as separate purchasable resources or
used as the primary subscription budget gate.

Site Knowledge indexed article count is a package capacity boundary, not a
separate purchasable consumption budget. Vector chunks and sync-per-run limits
remain implementation detail unless a future contract explicitly promotes them
to visible package capacity.

Site Knowledge index maintenance is measured separately from ordinary AI
inference credits. The canonical `npcink-cloud/site-knowledge-sync` ability
records run/provider/token/cost and vector-volume evidence with
`metering_class=site_knowledge_index_maintenance`, but those events do not write
AI-credit consume entries. Cloud derives this class from the ability name; a
caller-provided payload cannot request it. Site Knowledge search and downstream
writing or generation remain ordinary AI-credit consumers.

## Feature Rule Fields

Feature charge rules use `AI_CREDIT_FEATURE_CHARGE_RULES_VERSION=ai-credit-feature-charge-rules-v1`.

Each feature rule must declare:

- `feature_key`: stable product feature identifier.
- `capability_key`: existing runtime capability policy used for authorization and estimates.
- `charge_policy`: operator-readable policy name.
- `ledger_components`: allowed ledger components for realized usage.
- `limit_policy`: budget gate policy, currently AI credits required before execute.
- `budget_key`: commercial budget key, currently `ai_credits`.
- `contract_version`: feature rule contract version.

WeChat Pay and Alipay affect order confirmation and credit grants. They do not create a second AI usage billing path.

## Current Non-Consume Sources

Credit pack purchases and operator repairs are not AI usage components. They write explicit ledger events:

- `grant` with `source_type=credit_pack_purchase` or operator grant.
- `adjustment` with `source_type=credit_pack_refund` or operator repair.

Credit pack purchase grants include `validity_days`, `expiry_policy`, and
`grant_expires_at` metadata. The default customer credit-pack validity is 365
days after payment confirmation; this does not create a permanent wallet.

These entries affect net AI credit usage but do not appear in usage breakdown components.
