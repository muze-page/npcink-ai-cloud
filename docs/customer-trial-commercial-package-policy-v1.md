# Customer Trial Commercial Package Policy v1

Status: active for the next small-customer trial phase.

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
- Acts as the fallback package when Pro trial or Pro paid coverage ends.

### Pro

- User-initiated from Portal.
- First Pro activation receives one 14-day free trial.
- Trial coverage uses Pro entitlements during the trial window.
- Pro paid coverage is monthly.
- Initial public price is CNY 29 per month.
- Payment provider for this phase is Alipay.

### Plus

- Entry paid package for accounts that have outgrown Free.
- Managed by operator/Admin while self-serve Plus checkout is not finalized.
- Sits between Free and Pro for monthly AI credits, site headroom, and runtime
  concurrency.
- Customer-facing copy may say "contact support"; it must not show a Plus
  payment button until the Plus checkout contract is added.

### Agency

- Custom high-volume package for a small number of accounts.
- Managed by operator/Admin only.
- Not exposed as a normal self-serve checkout product.
- Customer-facing copy may say "contact us" or "custom plan"; it must not show
  an Agency payment button.

## State Model

```text
new registration
  -> Free active

Free active + user starts Pro trial
  -> Pro trialing, 14 days

Pro trialing + payment succeeds
  -> Pro active, monthly period

Pro trialing + no payment after trial end
  -> Free active

Free active + direct Pro payment succeeds
  -> Pro active, monthly period

Plus
  -> operator-managed active subscription

Agency
  -> operator-managed active subscription
```

Trial is not a standalone package. It is a Pro subscription state.

Trial expiry is reconciled lazily by the Cloud commercial service. When account
detail, Portal session, runtime authorization, or Pro monthly checkout touches
an account with an expired Pro trial, the service cancels the trial subscription
and restores the account's Free subscription before returning the current
coverage.

## Current Non-Goals

- Invoices.
- Seat or member lifecycle beyond the single customer email login path.
- WeChat Pay user-facing checkout.
- Complex dunning. Payment reminders may be sent by email.
- Self-serve Plus purchase.
- Self-serve Agency purchase.
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
- Portal can start exactly one Pro trial per account.
- Portal can create a Pro monthly payment order for CNY 29.
- Expired Pro trials fall back to Free instead of continuing to count as Pro
  coverage.
- A successful payment event activates Pro monthly entitlement without being
  blocked by the existing Free or Trial subscription.
- Plus remains operator-managed and absent from self-serve checkout.
- Agency remains operator-managed and absent from self-serve checkout.
- Real Alipay provider readiness is proven before collecting real payments.
