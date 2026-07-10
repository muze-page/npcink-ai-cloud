# Small Customer Trial Commercial Readiness v1

Status: active checklist for the next small real-customer trial.

Purpose: define the minimum commercial checks before inviting real customers to
use Free, trial or buy Plus/Pro, or pay an approved Agency quote.

## Product Rules

- Free is granted automatically after registration.
- Free never requires a trial or payment.
- Plus and Pro are self-serve from Portal at CNY 15 and CNY 29 per 30 days.
- Plus, Pro, and Agency share one 14-day paid-package trial per customer.
- Plus and Pro trials are self-serve; Agency trials require Admin approval.
- Paid coverage starts only after Alipay payment notify is verified and applied.
- Payment during a trial schedules the paid 30-day period from the trial end.
- Expired paid-package trials fall back to Free.
- Agency requires an account-bound, operator-approved, time-limited quote. The
  customer pays that quote from Portal.

## Alipay Configuration

Configure Alipay from Cloud Admin, not from deployment environment variables:

1. Open `/admin/service-settings`.
2. Save the Portal base URL in `登录配置`.
3. Open `支付配置`.
4. Enter the Alipay app id, gateway URL, Cloud application private key, and
   Alipay public key.
5. Copy the generated notify URL and return URL into the Alipay platform:
   - `https://<cloud-host>/open/payments/alipay/notify`
   - `https://<cloud-host>/open/payments/alipay/return`
6. Save and run `检查支付宝配置`.

The key values are stored in Cloud `service_settings` encrypted secret storage
and must not be committed. Deployment environment variables are not a payment
gateway configuration source.

## Required Checks

Run the production preflight after deploy and before inviting a paying trial
customer:

```bash
mkdir -p .tmp
cp deploy/release-smoke.env.example .tmp/release-smoke.env
chmod 600 .tmp/release-smoke.env

# Fill .tmp/release-smoke.env from the production secret store and a real
# mailbox login code. Do not commit the filled file.
NPCINK_CLOUD_ENV_FILE=.tmp/release-smoke.env \
  pnpm run smoke:small-trial-preflight -- \
    --base-url https://cloud.npc.ink \
    --require-smoke-env \
    --require-alipay-enabled
```

If the preflight reports that Alipay callbacks are not enabled, do not invite a
paying trial customer. Configure `/admin/service-settings`, run `检查支付宝配置`,
and rerun the preflight.

Run code gates:

```bash
pnpm run lint
pnpm run check:fast
.venv/bin/python -m pytest tests/domain/test_payment_gateways.py tests/domain/test_payment_service.py tests/domain/test_subscription_commerce.py -q
.venv/bin/python -m pytest tests/api/test_portal_routes.py::test_open_alipay_notify_marks_pro_monthly_order_paid -q
```

Run payment-provider checks in sandbox or a controlled low-value production
payment:

- Create a new Portal user and confirm Free is active.
- Start Plus trial, move it to Pro, and confirm the end time does not change.
- Create a Plus or Pro monthly order and confirm Alipay returns a real checkout URL.
- Complete payment.
- Confirm `/open/payments/alipay/notify` returns plain text `success`.
- Confirm the payment order is `paid`.
- Confirm direct purchase is active, or trial conversion is paid and scheduled
  from the trial end.
- Confirm the browser return lands on `/portal/billing` and does not mutate
  payment state by itself.
- Replay the same notify and confirm no duplicate entitlement or credit grant is
  created.
- Submit an amount-mismatch notify in sandbox and confirm it fails.

## Go / No-Go

Go only if all of the following are true:

- Free registration, shared paid-package trial, Plus/Pro purchase, Agency quote
  purchase, paid upgrade, renewal, scheduled downgrade, refund restoration, and
  trial expiry fallback are verified against the target deployment.
- Alipay notify is reachable from the Alipay platform.
- Alipay notify signature verification is enabled.
- Amount, currency, provider order, and event id checks are passing.
- Portal copy explains that Agency requires an approved quote and trial approval.
- Dunning remains email/manual for this phase.

No-go if any payment callback is accepted without signature verification, if
return URL is treated as payment truth, or if a failed payment can activate a
paid package.
