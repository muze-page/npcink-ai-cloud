# Alipay Payment and Portal Entry Hardening - 2026-07-11

Last updated: 2026-07-12

## Status

Accepted implementation history and production handoff record.

This document summarizes the July 11 investigation and implementation work
covering Alipay Page Pay settings, Portal/Admin authenticated entry behavior,
Alipay request signing, payment-order cancellation, and the Portal Billing
order list.

It records why the changes were made, the boundaries that must remain intact,
and the verification needed before production rollout. It must not contain
application private keys, Alipay public keys, session cookies, or other secret
values.

## Cloud Boundary

Npcink AI Cloud owns the hosted commercial service plane for:

- payment-order creation and state;
- provider checkout execution and callback verification;
- encrypted payment credentials;
- package and credit entitlement evidence;
- customer-visible billing and payment-order history.

This work does not create a second WordPress control plane, move WordPress
write authority into Cloud, or treat a browser return URL as payment truth.
Only a verified provider notification may confirm payment and grant a package
or credits.

## 1. Alipay Settings Surface

### Problems

The initial settings surface exposed the production Alipay gateway as an
editable field and displayed two callback URLs without enough explanation.
This led to three operator questions:

- whether the fixed gateway should be shown at all;
- why there are both `notify_url` and `return_url`;
- which URL should be entered as the Alipay console's authorization callback.

### Decisions

Commit `4a3e0d5a` (`Fix Alipay Page Pay settings guidance`) established the
following contract:

- Page Pay always uses
  `https://openapi.alipay.com/gateway.do`;
- the gateway is backend-owned and no longer an editable operator field;
- the callback URLs are derived from the Portal public base URL and displayed
  together with their distinct purposes;
- `notify_url` is the server-to-server payment result notification and the
  only payment confirmation path;
- `return_url` only brings the customer back to Portal and never proves that
  payment succeeded.

Production callback examples are:

```text
https://cloud.npc.ink/open/payments/alipay/notify
https://cloud.npc.ink/open/payments/alipay/return
```

Alipay's **authorization callback URL** belongs to user OAuth authorization.
The current Page Pay integration does not use Alipay user authorization, so it
does not require either payment callback to be entered as an authorization
callback. If an Alipay console field explicitly asks for an asynchronous
payment notification URL, use `notify_url`; if it asks for the browser's
synchronous return URL, use `return_url`.

### Key Roles

The three key concepts must not be mixed:

- **Application private key**: stored encrypted in Cloud and used to sign
  outgoing requests;
- **Application public key**: uploaded to the matching Alipay application;
- **Alipay public key**: stored encrypted in Cloud and used to verify Alipay
  callbacks and responses.

The App ID, application private key, and application public key registered for
that App ID must belong to the same key pair. The Alipay public key is not the
application public key.

## 2. Authenticated Entry Pages

### Observed Inconsistent State

An authenticated customer could open `/portal/login` and still see the login
form while Portal navigation and a logout action were visible. The inverse
state was also possible: a stale or invalid cookie could expose the shell and
navigation before the session had been validated.

The root causes were split across layers:

- public entry pages did not redirect an already authenticated session;
- the Admin proxy trusted cookie presence rather than a validated session;
- protected Portal and Admin layouts could render navigation while session
  resolution was still pending;
- stale Portal cookies did not consistently return the user to login with the
  original destination preserved.

### Accepted Behavior

Commit `7ea15fcd` (`Harden authenticated entry page routing`) implemented:

- authenticated visits to `/portal/login` and `/portal/register` redirect to
  `/portal` or a validated local `redirect` target;
- protected Portal routes use `PortalSessionBoundary` and hide the shell while
  session state is unresolved;
- invalid Portal sessions clear local session state and redirect to
  `/portal/login?redirect=...`;
- Admin login and layout validate `/admin/session` before showing protected
  navigation;
- the proxy no longer treats an Admin cookie's mere presence as proof of an
  authenticated session.

The reusable design rule is: **navigation visibility and entry-page redirects
must be driven by validated session state, never by cookie presence alone**.

## 3. Alipay `invalid-signature` Root Cause

### Production Evidence

Alipay returned `invalid-signature` and displayed a gateway verification
string that included:

```text
sign_type=RSA2
```

The Cloud request canonicalizer excluded both `sign` and `sign_type`. Local
reproduction proved that the generated signature verified against Cloud's
shorter string but failed against Alipay's actual verification string. Correct
credentials could therefore still fail every request.

The implementation also formatted `datetime.now(UTC)` without a timezone,
producing a wall-clock value eight hours behind the Alipay gateway's expected
China time.

### Fix

Request signing and callback verification now use separate canonicalization
rules:

- outgoing OpenAPI request signing excludes only `sign`, so `sign_type=RSA2`
  participates in the signature;
- provider callback verification excludes `sign` and `sign_type`, preserving
  the callback contract;
- Page Pay order creation and order closing use `Asia/Shanghai` timestamps.

The distinction is intentional. A single generic canonicalizer must not be
reintroduced for both directions.

Regression coverage reconstructs the complete checkout query and verifies the
RSA2 signature with `sign_type` included. It also checks that the timestamp is
generated in the Alipay gateway timezone.

### Configuration Check Limitation

The Admin "check Alipay configuration" action confirms that stored keys can be
parsed and used cryptographically. It cannot prove that the application public
key uploaded to Alipay matches the stored private key without making a real
Alipay request. A successful local configuration check is therefore necessary
but not sufficient for production readiness.

## 4. Payment-Order Cancellation Contract

### Previous Gap

The Billing page only showed "Cancel" when a pending order carried a
`subscription_order_id`. Pending credit-pack orders had no cancellation UI,
even though they also created provider checkout orders and expired after 30
minutes.

The frontend was inferring capability from subscription metadata. That made
the customer-visible behavior depend on an internal implementation detail.

### Additive API Contract

Payment-order serialization now includes an additive field:

```json
{
  "available_actions": ["continue_payment", "cancel"]
}
```

Portal uses this server-owned capability list rather than deriving actions
from `purchase_kind` or subscription metadata.

The unified cancellation endpoint is:

```text
POST /portal/v1/account/payment-orders/{order_id}/cancellation
```

It requires the normal Portal protections:

- validated Portal authentication;
- same-origin write guard;
- idempotency key;
- primary account ownership;
- a pending payment-order state.

Cancellation behavior is:

1. lock the account and payment order;
2. reconcile expiration first;
3. return the existing canceled state for a repeated cancellation;
4. reject paid or refunded orders with a conflict;
5. close a real provider order before changing local state;
6. mark the local order canceled, clear its checkout URL, and synchronize a
   linked pending subscription order;
7. record sanitized service-plane audit evidence;
8. never grant credits or package rights during cancellation.

If a real checkout URL exists but the payment provider is no longer configured
to close it safely, cancellation fails closed and the local order remains
pending. The service must never simulate a successful provider close for a
real external order.

The older subscription-order cancellation endpoint remains available for
compatibility, but new Portal UI uses the unified payment-order contract.

## 5. Portal Billing Order UX

### Previous Problems

- the status badge and the text below it rendered the same label;
- the four proportional desktop columns created excessive whitespace;
- credit-pack orders lacked cancellation;
- copy mentioned Alipay or WeChat Pay even when the individual order already
  identified its provider;
- a section named "Recent payment orders" hid canceled and expired orders,
  so it was not a truthful order history;
- important pending actions were hidden behind a disclosure.

### Implemented Layout

The payment-order surface is now always visible and separated into:

- **Pending payment orders**: actionable orders first;
- **Recent records**: paid, canceled, failed, refunded, and expired history.

Each order uses a bounded three-column desktop layout:

```text
order identity + one status badge | amount + time | available actions
```

On narrow screens the same content stacks vertically. The row includes:

- localized product title;
- one status badge;
- provider-specific explanatory text;
- provider label and shortened order reference;
- amount and expiration or creation time;
- primary "Continue payment" action when available;
- low-emphasis "Cancel order" followed by an inline confirmation step.

After cancellation, the order moves from the pending group to recent records
instead of disappearing. This preserves customer feedback and an honest local
history.

## 6. Verification Evidence

The final implementation passed:

```text
Payment gateway unit tests:             9 passed
Payment service target/full tests:      passed
Portal API tests:                       61 passed
Portal Billing interaction E2E:         1 passed
Frontend unit contracts:                passed
Frontend ESLint and TypeScript:          passed
Cloud perimeter:                        9 passed
check:fast contract suite:              70 passed, 1 skipped
check:fast domain suite:                171 passed, 3 skipped
```

Earlier authenticated-entry verification recorded for `7ea15fcd` included
Portal login E2E, Admin operator E2E, frontend contracts, `check:fast`, and the
Cloud seam/perimeter gates.

## 7. Production Rollout Checklist

Before deployment:

1. confirm the intended commits are on `master` and CI is green;
2. follow `docs/cloud-production-release-policy-v1.md`;
3. verify the production App ID and key roles without copying secrets into
   tickets, logs, or this repository;
4. confirm the Portal public base is `https://cloud.npc.ink` and the generated
   `notify_url` and `return_url` use the accepted paths;
5. verify production clock synchronization;
6. deploy application code rather than editing production source directly.

After deployment:

1. create a **new** low-value order; old checkout URLs retain their original
   invalid signatures and must not be reused;
2. confirm the Alipay checkout opens without `invalid-signature`;
3. cancel one unpaid credit-pack order and confirm it moves to recent records;
4. complete one low-value payment and verify that only the signed asynchronous
   notification grants the package or credits;
5. verify browser return only shows a pending/refresh notice until the provider
   notification has been processed;
6. inspect sanitized audit and order evidence without exposing credentials.

## 8. Reusable Engineering Principles

- Fix protocol mismatches from provider evidence and a minimal cryptographic
  reproduction, not by repeatedly replacing credentials.
- Keep incoming and outgoing signature contracts separate when the provider
  defines different canonicalization rules.
- Let backend state expose customer-available actions; do not make the UI infer
  capabilities from unrelated metadata.
- Close external state before committing the corresponding local cancellation.
- Treat verified asynchronous notifications as payment truth; browser returns
  are navigation only.
- Render authenticated shells only after session validation.
- Prefer fixed, backend-owned infrastructure endpoints over editable settings
  when the endpoint has no legitimate operator variation.
- Keep customer order history honest: actions belong to pending state, while
  terminal states remain visible as records.

## 9. July 11-12 Payment, Credit, and Price Consistency Closeout

### Why The Second Investigation Was Needed

After the signing fix reached production, a low-value credit-pack payment
provided an important counterexample to the Portal display:

- the internal payment order was already `paid`;
- the Alipay trade number and processed payment event were persisted;
- the credit ledger contained a `+10,000` purchase grant;
- subsequent runtime activity had consumed `23` credits;
- the browser still showed a pending notice and the visible quota still looked
  like the Free package allowance.

The payment itself was not lost. Three different read models had been confused:

1. the browser return query was being treated as display state instead of
   resolving the persisted order;
2. the positive ledger grant was accounting evidence, but runtime quota still
   had no durable remaining-balance record for the purchased credits;
3. the Portal usage header and quota card used package-period or net-ledger
   values that could not describe package allowance plus paid credits.

The reusable debugging rule is: **prove provider state, order state, event
state, ledger evidence, and spendable balance separately before changing
credentials or replaying checkout**.

### Accepted Truth Split

The consistency work formalized three related but distinct truths:

- `payment_orders`: sale and provider-state truth;
- `paid_credit_grants`: remaining spendable balance and expiry truth;
- `credit_ledger_entries`: immutable grant, consumption, adjustment, and audit
  evidence.

A ledger grant alone must not be interpreted as current spendable headroom.
Conversely, the paid-credit balance must always remain traceable to a verified
internal payment order and its ledger evidence. This is intentionally not a
general-purpose wallet.

The detailed architecture decision is recorded in
`docs/decisions/001-payment-backed-credit-grants-and-package-pricing.md`.

## 10. Paid-Credit Balance And Consumption Policy

Commit `1e0d100d` (`fix(commercial): reconcile payments credits and pricing`)
added migration `20260711_0059` and the `paid_credit_grants` model.

Accepted behavior:

- a successfully verified credit-pack payment creates one idempotent grant
  linked to the account and payment order;
- old successful purchases can be reconstructed lazily from trusted payment
  and ledger evidence after the migration;
- paid credits are account-scoped and remain usable across subscription-period
  renewal or a package change until their own expiry;
- the default purchase validity remains 365 days;
- runtime spends the current package allowance first;
- only the overage is allocated to paid-credit grants;
- multiple paid grants use earliest-expiry-first ordering;
- operator grants and adjustments continue to affect package net usage and are
  not silently reclassified as purchased credits;
- a refund reduces the remaining grant while retaining order, ledger, and
  audit evidence.

Portal now exposes these values separately:

```text
package remaining + paid-credit remaining = total currently available
```

The nearest paid-credit expiry is also visible. This avoids the previous
failure mode where `+10,000` appeared in the ledger while the headline value
showed only the package allowance or `0`.

## 11. Sales Price And Model Cost Budget

The Admin package page previously labeled `max_cost_per_period` as a package
fee. That field is an internal provider-cost monitoring guardrail in USD, not
the amount charged to a customer. The actual customer price lived in
`plan_offers.amount`, while Portal copy also embedded fixed Plus and Pro values.

The accepted split is:

- **sales price (CNY / 30 days)**: customer-facing price used for future
  checkout orders;
- **model cost budget (USD / period)**: internal provider-cost threshold that
  never changes the payment amount.

Publishing a paid package version now synchronizes the canonical standard
offer's amount and `plan_version_id`. Portal cards read live offer amount,
currency, and trial days instead of fixed `15 / 29 / 14` values. Existing
payment orders retain their purchase-time price and subject snapshots.

If a standard offer is absent or inactive, Portal says that the package is not
currently purchasable rather than showing a misleading `available` badge.

Provider-facing subjects for new orders use stable Chinese customer copy, such
as `Npcink AI Cloud 小积分包（10,000 AI 积分）`; editable internal catalog labels
do not rewrite existing orders.

## 12. Return-Page Reconciliation And Success Feedback

The browser return URL remains navigation only. Portal now resolves the exact
order through:

```text
GET /portal/v1/account/payment-orders/{order_id}
```

The return-page state machine is:

- `pending`: poll every 3 seconds for at most 20 attempts;
- `paid`: stop polling, refresh session, entitlements, quota, and order list,
  then remove the return query from the address bar;
- canceled, failed, or refunded: show a terminal explanation and a safe next
  action;
- timeout: preserve the order reference and offer manual refresh/support.

Commit `ffcdab24` (`test(portal): close payment return feedback loop`) completed
the customer feedback loop. A successful credit-pack notice now keeps showing
after URL cleanup and groups the three important facts in one place:

- credits added by this payment;
- current total available credits after reconciliation;
- nearest paid-credit expiry.

The three metrics render only after the entitlement refresh completes, so the
page does not briefly present the pre-payment balance as current truth. Missing
quota data renders as unavailable rather than a false zero. The asynchronous
status container uses polite live-region semantics for accessibility.

## 13. Portal Navigation And Order-History Details

The surrounding Portal polish was kept subordinate to the payment state
machine:

- desktop navigation uses `logo | centered menu | account actions` in one Grid
  row;
- tablet keeps a bounded horizontal navigation row;
- mobile keeps the menu drawer;
- checkout opens Alipay in a new tab, with an explicit fallback when the
  browser blocks the popup;
- payment orders have `all / pending / paid / closed` views;
- canceled and expired unpaid orders remain visible in Portal for 7 days but
  are not deleted from accounting or audit storage;
- actions are owned by the backend `available_actions` contract rather than
  inferred from frontend order metadata.

These details reduce confusion without turning Portal into a second billing
engine or WordPress control plane.

## 14. Verification And Regression Coverage

The consistency commit and feedback-loop commit passed the following combined
local evidence:

```text
Focused payment/Portal backend suite: 104 passed
Cloud contract suite:                  70 passed, 1 skipped
Cloud domain suite:                   184 passed, 3 skipped
Cloud API suite:                      486 passed
Cloud perimeter:                       9 passed
Portal workspace Playwright:           8 passed
Admin operator Playwright:              9 passed
Ruff:                                  passed
Mypy:                                  204 source files passed
Frontend contracts/type-check/lint:    passed
```

The new Playwright scenario is deliberately behavioral rather than a source
regex alone. Its mocked provider/order seam performs:

```text
pending -> next poll paid -> entitlement refresh ->
10,000 credited + 12,419 total available + expiry visible -> URL cleaned
```

Backend tests separately retain the cryptographic callback, exact-order access,
grant idempotency, cross-period validity, expiry, price-to-offer synchronization,
new-order price snapshot, package-first consumption, and paid-credit allocation
coverage.

## 15. Current Repository And Release Handoff

As of 2026-07-12, the final consistency work is committed on:

```text
branch:  codex/payment-credit-price-consistency
commits: 1e0d100d, ffcdab24
```

At this checkpoint the branch has not been pushed, merged to `master`, promoted
to `production`, or deployed. Therefore the code phase is closed, but production
delivery is not.

The active worktree also contains unrelated provider and Site Knowledge changes.
They must not be staged with this commercial history or used as the production
release source. Follow the repository rule and use a clean worktree for release
or promotion work.

Required release sequence:

1. push the focused branch and open a PR to `master`;
2. require green CI and review the exact release scope;
3. merge to `master` before promoting to `production`;
4. include `Approved for production validation by operator.` in the production
   promotion PR body;
5. let the formal production workflow deploy application code and run Alembic
   migration `20260711_0059`;
6. create a new low-value payment and verify checkout, signed notification,
   exact-order reconciliation, `10,000` credit arrival, package-first spending,
   total balance, and expiry display;
7. retain the previous production release as the rollback target until the
   smoke result is recorded.

The production policy's upgrade trigger is now relevant because paid credits
have been exercised on the production service. Before expanding beyond bounded
operator validation, enable or explicitly schedule GitHub branch protection
and production-environment approval instead of relying indefinitely on the
lightweight manual gate.

No additional commercial feature work is recommended before this release
closure. The next action is publish, migrate, and perform the production smoke,
not add another payment state or balance abstraction.
