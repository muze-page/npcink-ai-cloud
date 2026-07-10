# Cloud Open Callback Boundary v1

Status: active.

Purpose: define the public callback namespace for third-party login and payment
providers without turning Cloud into a broad anonymous API surface.

## Public Callback Prefix

Cloud owns the public callback prefix:

```text
/open
```

This prefix is only for third-party callbacks that must be reachable from
provider platforms. It is not a general public API, not a WordPress control
plane, and not a local ability or workflow registry.

Current path contract:

```text
/open/auth/qq/callback
/open/auth/wechat/callback
/open/payments/alipay/notify
/open/payments/alipay/return
/open/payments/wechat/notify
```

## Auth Callback Rules

Authentication callbacks use provider-specific paths under `/open/auth`.

- QQ login callback is active at `/open/auth/qq/callback`.
- The retired `/portal/v1/auth/qq/callback` path is rejected.
- WeChat login callback is reserved and must fail closed until its provider
  configuration, state validation, and account-binding contract are implemented.

Auth callbacks may create or bind a bounded Portal `user` session. They must not
create WordPress users, write WordPress content, or grant WordPress authority.

## Payment Callback Rules

Payment callbacks use provider-specific paths under `/open/payments`.

- Payment notify callbacks are server-to-server provider notifications.
- Payment return callbacks are browser return surfaces and are not payment truth.
- Alipay browser return may redirect back to Portal billing with redacted order
  hints for user experience, but it must not mark orders paid, issue credits,
  or update subscriptions.
- Payment callback paths must fail closed unless provider signature
  verification and order-state reconciliation are enabled for that provider.
- Alipay notify may mark orders paid only when real Alipay mode is configured,
  RSA2 signature verification succeeds, and order amount/currency/identity
  checks pass.
- Real Alipay mode is configured only through the Cloud Admin
  `payment_alipay` service setting. Deployment environment variables are not a
  payment callback enablement source.
- WeChat Pay notify remains reserved and must fail closed until its provider
  signature verification and reconciliation path are implemented.

Payment truth remains Cloud commercial runtime storage. Payment callbacks must
verify provider signatures, enforce idempotency, compare amount/currency/order
identity, and write service audit evidence before changing commercial state.

## Boundary

Allowed:

- provider OAuth callback handling;
- provider payment notification handling after explicit implementation;
- bounded Portal session or commercial state mutation only after provider
  validation succeeds;
- redacted audit evidence.

Forbidden:

- anonymous runtime execution;
- WordPress writes;
- ability, workflow, prompt, router, MCP, or OpenClaw truth;
- accepting payment state changes without provider verification;
- storing raw secrets or exposing credential values.
