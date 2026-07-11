# ADR 001: Payment-backed credits and package pricing

Status: accepted

Date: 2026-07-11

## Context

The commercial service previously recorded a credit-pack purchase only as a
positive ledger entry. Runtime quota checks still used the package-period
limit, so a successful purchase could appear in accounting history without
increasing usable credits. Package administration also exposed a provider-cost
budget using a currency label that made it look like the customer price.

## Decision

1. A successful credit-pack payment creates an idempotent
   `paid_credit_grants` balance tied to the internal payment order. Available
   paid credits are consumed after the active package allowance and in earliest
   expiry order. The credit ledger remains the immutable usage/evidence trail.
2. Existing successful purchases can be reconstructed lazily from trusted
   payment-order and ledger evidence. This is a compatibility backfill, not a
   second source of sale truth.
3. The package editor exposes two separate commercial values:
   - **Sales price (CNY):** the amount charged to the customer and snapshotted
     onto a new payment order.
   - **Model cost budget (USD):** an internal provider-cost guardrail for one
     package period. It is not a customer price or wallet balance.
4. Publishing a paid package version synchronizes its standard Portal offer.
   New checkouts use that offer; existing orders keep their purchase-time
   amount and subject snapshots.
5. The Alipay return page resolves and polls the exact internal order. Query
   parameters from the browser are only navigation hints and never proof of a
   successful payment.

## Consequences

- Portal quota shows package remaining, paid-credit remaining, and total
  available separately.
- Paid-credit grants remain part of Cloud commercial service-plane truth; no
  WordPress write/control-plane responsibility moves into Cloud.
- Refund handling can reduce only unspent paid-credit balance. Accounting and
  audit evidence is retained even when Portal history hides old closed orders.
- Sales price and model cost budget may intentionally use different currencies
  because they answer different business questions.

## Rollback

The UI and exact-order polling can be reverted independently. Before removing
the grant table, stop new grant creation and preserve its rows for reconciliation;
do not infer remaining paid credits solely from a net ledger total.
