# Payment Gateway Contract v1

Status: active

This contract defines the boundary between Npcink AI Cloud payment orders and
external payment providers.

The code truth is `app/domain/commercial/payment_gateways.py`.

## Boundary

The gateway layer owns provider-specific order creation, payment callback
verification, refund creation, and refund callback verification.

The commercial service still owns:

- payment order persistence;
- subscription activation;
- credit pack grants;
- refund adjustments;
- audit events;
- credit ledger writes.

Do not let Alipay, WeChat Pay, SDK callback payloads, or signing details leak
into credit ledger or entitlement logic.

## Provider Contract

Every provider must implement:

- `create_order(request)`: returns `external_order_no`, optional `checkout_url`,
  and provider metadata.
- `verify_payment_callback(payload)`: returns normalized order number, trade
  number, event id, amount, status, and occurred time.
- `create_refund(request)`: returns `external_refund_no` and provider metadata.
- `verify_refund_callback(payload)`: returns normalized refund number, provider
  refund number, event id, amount, status, and occurred time.

Supported provider keys are:

- `alipay`
- `wechat_pay`
- `manual`

`wechat` and `wxpay` are accepted aliases for `wechat_pay`.

## Current Provider Mode

Providers run in simulated mode by default.

Alipay can run in real page-pay mode only when the operator saves the
`payment_alipay` service setting through the Cloud Admin service settings
surface. App id, RSA private key, Alipay RSA public key, gateway URL, notify
URL, and return URL are stored in Cloud runtime storage; private/public key
material is saved in the encrypted service-setting secret store and is not
read from deployment environment variables. Real Alipay mode signs
`alipay.trade.page.pay` orders with RSA2 and verifies asynchronous notify
callbacks before any payment order is marked paid.

Deployment environment variables are not a payment gateway configuration
source. If `payment_alipay` is missing, disabled, incomplete, or fails key
validation, public Alipay callbacks must fail closed and checkout orders must
not depend on stale `.env` values.

WeChat Pay remains simulated/reserved in this phase.

Real provider integration must stay behind this contract. It must not change
the payment order, credit pack, subscription, entitlement, or credit ledger
state machine.
