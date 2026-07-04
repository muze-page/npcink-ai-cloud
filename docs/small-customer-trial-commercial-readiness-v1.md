# Small Customer Trial Commercial Readiness v1

Status: active checklist for the next small real-customer trial.

Purpose: define the minimum commercial checks before inviting real customers to
use Free, start Pro trial, or pay for Pro monthly service.

## Product Rules

- Free is granted automatically after registration.
- Free never requires a trial or payment.
- Pro is self-serve from Portal.
- First Pro activation gets one 14-day trial.
- Pro monthly price is CNY 29.
- Pro paid coverage starts after Alipay payment notify is verified and applied.
- Expired Pro trials fall back to Free.
- Agency is operator-managed only and has no self-serve checkout button.

## Alipay Configuration

Set these environment variables before collecting real payments:

```text
NPCINK_CLOUD_ALIPAY_PAYMENT_ENABLED=true
NPCINK_CLOUD_ALIPAY_GATEWAY_URL=https://openapi.alipay.com/gateway.do
NPCINK_CLOUD_ALIPAY_APP_ID=<alipay app id>
NPCINK_CLOUD_ALIPAY_PRIVATE_KEY=<cloud app RSA private key>
NPCINK_CLOUD_ALIPAY_PUBLIC_KEY=<alipay platform RSA public key>
NPCINK_CLOUD_ALIPAY_NOTIFY_URL=https://<cloud-host>/open/payments/alipay/notify
NPCINK_CLOUD_ALIPAY_RETURN_URL=https://<cloud-host>/open/payments/alipay/return
```

Do not commit key values. Keep private keys in deploy secrets only.

## Required Checks

Run code gates:

```bash
pnpm run lint
pnpm run check:fast
.venv/bin/python -m pytest tests/domain/test_payment_gateways.py tests/domain/test_payment_service.py -q
.venv/bin/python -m pytest tests/api/test_portal_routes.py::test_open_alipay_notify_marks_pro_monthly_order_paid -q
```

Run payment-provider checks in sandbox or a controlled low-value production
payment:

- Create a new Portal user and confirm Free is active.
- Start Pro trial and confirm Pro trialing status.
- Create a Pro monthly order and confirm Alipay returns a real checkout URL.
- Complete payment.
- Confirm `/open/payments/alipay/notify` returns plain text `success`.
- Confirm the payment order is `paid`.
- Confirm the subscription is Pro `active`.
- Confirm the browser return lands on `/portal/billing` and does not mutate
  payment state by itself.
- Replay the same notify and confirm no duplicate entitlement or credit grant is
  created.
- Submit an amount-mismatch notify in sandbox and confirm it fails.

## Go / No-Go

Go only if all of the following are true:

- Free registration, Pro trial, Pro paid activation, and trial expiry fallback
  are verified against the target deployment.
- Alipay notify is reachable from the Alipay platform.
- Alipay notify signature verification is enabled.
- Amount, currency, provider order, and event id checks are passing.
- Portal copy and support messaging explain that Agency is custom only.
- Dunning remains email/manual for this phase.

No-go if any payment callback is accepted without signature verification, if
return URL is treated as payment truth, or if a failed payment can activate Pro.
