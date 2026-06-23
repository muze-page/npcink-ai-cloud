# AI Credit Charge Contract v1

Status: active

This contract defines how new AI abilities or cloud features become billable in Magick AI Cloud.

Cloud remains the billing and runtime detail owner. This contract does not move ability, workflow, approval, or WordPress write truth out of the local/plugin side.

## Source Of Truth

The code truth is `app/domain/commercial/credits.py`.

Every billable AI capability must be represented by:

- `AI_CREDIT_COMPONENT_POLICY_REGISTRY` for ledger components.
- `AI_CREDIT_CAPABILITY_POLICY_REGISTRY` for runtime capability classification.

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
3. Include focused tests covering estimate, ledger entry, and idempotency.
4. Do not charge from frontend input. The server owns amount, rate, and ledger delta.
5. Grants, refunds, and operator adjustments must stay separate from consume components.

## Current Non-Consume Sources

Credit pack purchases and operator repairs are not AI usage components. They write explicit ledger events:

- `grant` with `source_type=credit_pack_purchase` or operator grant.
- `adjustment` with `source_type=credit_pack_refund` or operator repair.

These entries affect net AI credit usage but do not appear in usage breakdown components.
