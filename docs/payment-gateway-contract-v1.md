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

## Customer-facing Payment Subjects

New payment orders use a stable provider-facing subject that is separate from
editable internal catalog labels. The current Alipay-facing convention is:

- `Npcink AI Cloud 小积分包（10,000 AI 积分）` and the equivalent medium or
  large credit-pack descriptor using the purchase-time credit snapshot;
- `Npcink AI Cloud Plus 月度套餐` and the equivalent paid-tier descriptor for
  monthly subscription orders.

The same subject snapshot must be sent to the payment provider and persisted on
the Cloud payment order. Existing orders keep their original subject and are
not rewritten when this convention or an internal catalog label changes.

## Portal Order History

The Portal payment-order list is a filtered customer view, not the accounting
retention source. It supports `all`, `pending`, `paid`, and `closed` status
groups with independent pagination and server-computed counts.

Canceled and expired unpaid orders remain visible to the customer for 7 days.
After that window they are hidden from Portal list responses, but the database
record, payment evidence, audit trail, subscription relationship, and admin
history are not deleted. Paid and refunded orders are not subject to this
7-day customer-visibility cutoff.
