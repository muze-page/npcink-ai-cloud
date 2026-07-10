# Customer Trial Commercial Package Policy v1

Status: active for the paid-package validation phase.

Purpose: freeze the current Free / Plus / Pro / Agency commercial posture so future
agents do not reintroduce canceled MVP work or turn Cloud into a broad
commercial front office.

## Positioning

This phase targets a small number of real customer trials.

Cloud may own customer registration, package entitlement, subscription state,
payment-order evidence, and customer Portal package actions. Cloud must remain
the hosted runtime and service-plane layer. It must not become a WordPress
control plane, ability registry, workflow registry, prompt/router truth, or
WordPress write owner.

## Packages

### Free

- Granted automatically when a user registers.
- Permanent and free.
- Requires no trial, checkout, or payment.
- Acts as the fallback package when paid trial or paid coverage ends.

### Pro

- User-initiated from Portal.
- Available through a published self-serve monthly offer.
- Pro paid coverage is monthly.
- Initial public price is CNY 29 per month.
- Payment provider for this phase is Alipay.

### Plus

- Entry paid package for accounts that have outgrown Free.
- Available through a published self-serve monthly offer.
- Initial public price is CNY 15 per month.
- Sits between Free and Pro for monthly AI credits, site headroom, and runtime
  concurrency.

### Agency

- Custom high-volume package for a small number of accounts.
- Requires an operator-approved, account-bound, time-limited quote.
- The customer pays an approved quote from Portal; verified payment activates
  the exact quoted Agency plan version automatically.
- It is not exposed as an anonymous fixed-price offer while unit economics and
  account eligibility remain operator-reviewed.

## Trial Policy

- Plus, Pro, and Agency may each be selected as the target of a 14-day trial.
- A customer receives one paid-package trial in total, not one trial per tier.
- Trial eligibility is permanently claimed by account and principal. Deleting,
  canceling, expiring, or converting a trial does not restore eligibility.
- Plus and Pro trials are self-serve. Agency trials require operator approval.
- Moving upward during a trial keeps the original end time and carries used
  trial credits forward; it does not reset time or credits.
- A paid order completed during a trial starts its paid 30-day period when the
  trial ends. The selected paid tier may be reflected immediately for the
  remaining trial window without extending that window.
- Trial expiry without payment restores Free coverage.
- Trial credit limits are offer or quote data. Initial self-serve limits are
  3,000 credits for Plus and 5,000 credits for Pro. Agency trial quotes must set
  an explicit limit and may not exceed 20,000 credits in this phase.

## State Model

```text
new registration -> Free active
Free + Plus/Pro trial -> selected tier trialing, 14 days
Free + approved Agency trial -> Agency trialing, 14 days
trialing + higher trial tier -> higher tier, original trial end retained
trialing + payment succeeds -> paid coverage scheduled from trial end
trialing + no payment at trial end -> Free active
Free + paid offer succeeds -> paid tier active, 30-day period
paid tier + same tier payment -> renew from existing period end
paid tier + higher tier payment -> upgrade immediately; preserve period end
paid tier + downgrade request -> apply at current period end
```

Trial is not a standalone package. It is a subscription state for one of the
three paid package tiers.

Trial expiry is reconciled lazily by the Cloud commercial service. When account
detail, Portal session, runtime authorization, or package checkout touches an
account with an expired trial, the service cancels the trial subscription
and restores the account's Free subscription before returning the current
coverage.

## Subscription Change Rules

- Tier order is `free < plus < pro < agency`.
- Free-to-paid purchases charge the full published or quoted 30-day amount.
- Paid upgrades are immediate and charge the positive prorated price
  difference for the remaining period.
- Same-tier renewal extends from the existing period end instead of discarding
  prepaid time.
- Downgrades take effect at period end and do not remove current paid rights
  early.
- Full refunds revoke the purchased coverage and restore the prior effective
  package or Free.
- When package orders form an upgrade or renewal chain, refunds must be handled
  from the latest live order backward so an older refund cannot overwrite later
  paid coverage.
- Unpaid checkout orders expire after 24 hours and no longer block a new
  package order.
- Browser return URLs never activate rights. Only a verified provider callback
  may mark an order paid and apply the subscription transition.

## Current Non-Goals

- Invoices.
- Seat or member lifecycle beyond the single customer email login path.
- WeChat Pay user-facing checkout.
- Complex dunning. Payment reminders may be sent by email.
- Anonymous fixed-price Agency purchase.
- Automatic renewal, annual billing, coupons, invoices, and prorated refunds.
- Cloud-side WordPress publishing or any local approval replacement.

## Payment Boundary

Payment orders, subscription activation, entitlement snapshots, and audit remain
in Cloud commercial service code.

Provider-specific Alipay signing, checkout, and callback verification stay
behind `app/domain/commercial/payment_gateways.py` and the payment gateway
contract. Do not leak provider SDK payloads into entitlement or credit ledger
logic.

Providers remain simulated by default. Alipay real page-pay mode can be enabled
only with explicit configuration. A customer trial that collects real money must
use the configured Alipay RSA2 signing/verification path and pass callback
replay, amount/currency matching, and callback processing tests.

## Verification Gate

Before inviting paying trial customers:

- Portal registration creates a Free subscription automatically.
- Portal can claim exactly one paid-package trial per account and principal.
- Portal can select Plus or Pro for that trial; Agency requires approval.
- Portal can create Plus and Pro monthly orders from server-owned offers.
- Agency can be requested, quoted by an operator, paid in Portal, and activated
  from the verified callback.
- Expired trials fall back to Free instead of continuing paid-tier coverage.
- Upgrade, renewal, scheduled downgrade, and full-refund restoration preserve
  the defined subscription state transitions.
- Real Alipay provider readiness is proven before collecting real payments.
