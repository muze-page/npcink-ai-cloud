# Commercial Billing and Payment Stage Summary

Date: 2026-06-23

Status: local stage summary. This document records the recent commercial billing,
AI credit, credit pack, payment order, and payment gateway decisions before real
Alipay and WeChat Pay integration.

## Context

The product direction for commercial packaging is:

- provide three visible service levels: Free, Pro, and Agency;
- keep the existing `Agency` naming instead of renaming it to Custom;
- give different monthly AI credit grants per level;
- allow users to buy additional credit packs;
- keep most feature access open across tiers, except commercial limits such as
  bound sites, vector capacity, resource quotas, and AI credit consumption;
- use AI credits as the main control mechanism for AI search, hosted runtime,
  site knowledge, image recommendations, future AI abilities, and cloud-side
  billable features.

The boundary remains:

- Cloud owns commercial read models, runtime billing details, payment order
  state, and credit ledger detail;
- Cloud must not become a second ability registry, workflow registry, or
  WordPress control plane;
- WordPress Addon should show summaries and link to Cloud details, not own the
  payment, usage, or billing detail surface;
- Core/Adapter governed WordPress writes remain separate from Cloud billing.

## Local Commits

Recent local commits for this stage:

- `d8df7ea Add credit pack purchase flow`
- `2262a30 Close out credit order and charge rules`
- `d5d0ba9 Add payment gateway contract`

At the time this summary was written, `master` was ahead of `origin/master` by
three commits.

## Implemented Scope

### Credit Packs

Cloud now has a credit pack catalog and a credit pack payment order flow.
Credit pack purchase does not immediately grant credits. Credits are granted
only after the payment order is marked paid.

The current credit pack ledger behavior is:

- payment order created: `payment_orders.status=pending`;
- payment success: `credit_ledger_entries.event_type=grant`,
  `source_type=credit_pack_purchase`;
- refund success: `credit_ledger_entries.event_type=adjustment`,
  `source_type=credit_pack_refund`;
- credit pack grant/refund entries are idempotent by deterministic ledger keys.

### Payment Orders and Portal Read Model

Portal can read recent payment orders for the selected site/account through:

- `GET /portal/v1/sites/{site_id}/payment-orders`

The Portal usage page shows:

- credit pack catalog;
- recent payment orders;
- payment status detail;
- credit ledger detail.

Pending orders now return a `status_detail` payload that explains the order is
waiting for provider confirmation. This is intentionally not a real checkout
integration yet.

### Credit Ledger Explainability

Credit ledger serialization now distinguishes:

- `monthly_plan_grant`;
- `credit_pack_purchase`;
- `ai_usage`;
- `refund_adjustment`;
- `operator_adjustment`;
- `refund`;
- `other`.

Each ledger entry includes:

- `category`;
- `category_label`;
- `direction`;
- `explanation`.

Ledger summary includes `category_totals`, so Portal and Addon summaries do not
need to guess ledger meaning from raw `source_type` strings.

### Future AI and Cloud Feature Charge Rules

`app/domain/commercial/credits.py` now contains feature-level charge rules:

- `AI_CREDIT_FEATURE_CHARGE_RULES_VERSION`;
- `AI_CREDIT_FEATURE_CHARGE_RULES`;
- `AI_CREDIT_FEATURE_CHARGE_RULE_REQUIRED_FIELDS`;
- `list_ai_credit_feature_charge_rules()`.

The charge-rule contract requires every new billable AI or cloud feature to map
to:

- an existing runtime capability policy;
- allowed ledger components;
- an AI credit budget key;
- a limit policy.

This prevents future features from creating ad hoc billing logic in route
handlers, workers, provider clients, or frontend code.

Related contract:

- `docs/ai-credit-charge-contract-v1.md`

### Payment Gateway Contract

`app/domain/commercial/payment_gateways.py` now defines the payment gateway
contract for:

- `alipay`;
- `wechat_pay`;
- `manual`.

Accepted aliases:

- `wechat`;
- `wxpay`.

The provider contract covers:

- `create_order`;
- `verify_payment_callback`;
- `create_refund`;
- `verify_refund_callback`.

The current provider mode is simulated. It standardizes order, callback, and
refund payloads, but does not call real Alipay or WeChat Pay APIs yet.

Payment order and refund creation now pass through the gateway contract and
store provider metadata under `metadata.payment_gateway`.

Related contract:

- `docs/payment-gateway-contract-v1.md`

## Verification Already Run

The following verification passed during this stage:

- `uv run pytest tests/domain/test_ai_credit_policy.py tests/domain/test_payment_service.py tests/api/test_portal_routes.py -q`
- `uv run pytest tests/api/test_payment_routes.py -q`
- `uv run pytest tests/domain/test_payment_gateways.py tests/domain/test_payment_service.py tests/api/test_payment_routes.py -q`
- `uv run pytest tests/api/test_portal_routes.py tests/domain/test_ai_credit_policy.py -q`
- `uv run ruff check app tests`
- `uv run mypy app/domain/commercial/payment_gateways.py`
- `bash scripts/mypy-targeted.sh --profile commercial-runtime`
- `pnpm --dir frontend run type-check`
- `pnpm --dir frontend run lint`
- frontend i18n, Portal proxy, package, copy surface, and Portal boundary
  contract scripts.

## Eval Lab Review

`npcink-eval-lab` exists locally at:

- `/Users/muze/gitee/npcink-eval-lab`

The following local eval-lab checks were run:

- `project_quality_gate` against `npcink-ai-cloud`;
- `project_boundary_review_triad` with `dry_run=true`.

Results:

- triad dry-run reported zero findings, but this was only placeholder evidence,
  not provider-backed AI review;
- quality gate reported one item needing review:
  tracked files contain an `sk-...` shaped marker.

Manual inspection found the marker at:

- `tests/api/test_runtime_execute.py`

It is a fake test fixture used for secret-redaction behavior, not a real
provider key. It may still be worth changing to a non-`sk-` shaped fixture later
to reduce scanner noise.

Recommendation:

- use eval-lab provider-backed triad review before merging real Alipay/WeChat
  callback verification, not for every small internal refactor;
- run it with an explicit `project_label=npcink-ai-cloud`, because the dry-run
  report showed a misleading default project label.

## Known Gaps

### Real Payment Integration Is Not Done

The current gateway providers are simulated. Real Alipay and WeChat Pay still
need:

- merchant configuration;
- SDK or HTTP client integration;
- signing and verification;
- certificate/public-key handling;
- async callback routes;
- callback replay protection;
- amount, currency, and order-number matching;
- provider error mapping;
- refund request and refund callback handling.

### Callback Verification Must Become Cryptographic

Current callback verification is field normalization only. For real provider
mode, callback verification must fail unless provider signature verification
passes.

### Callback Routes Are Not Yet Exposed

The existing internal `mark-paid` and `mark-refund-succeeded` endpoints remain
simulation/operator endpoints. Real provider callback routes should be added as
separate provider-facing routes that:

- validate the provider;
- verify signature;
- locate order/refund by external number;
- enforce amount/currency match;
- call existing internal state transition methods only after verification.

### Replay and Idempotency Need Provider-Level Rules

Payment events already have idempotency handling, but real callbacks should
also define:

- provider event id extraction rules;
- event replay behavior;
- missing event id fallback;
- raw callback retention/sanitization policy.

### Secret Scanner Noise

The test fixture `sk-testtesttesttesttesttesttest` is safe but triggers the
eval-lab quality gate. Consider replacing it with a non-secret-shaped string
while preserving the redaction test intent.

## Recommended Next Steps

1. Keep the current three commits as a clean local milestone.
2. Decide whether to push/open PR before real payment integration.
3. Replace the `sk-...` shaped fake key fixture to reduce local quality-gate
   noise.
4. Start real Alipay integration first:
   - config model;
   - provider implementation behind `PaymentGatewayProvider`;
   - signature verification;
   - async notify route;
   - callback idempotency tests.
5. Then add WeChat Pay using the same gateway contract.
6. Run provider-backed `npcink-eval-lab` triad review after the first real
   callback route exists and before merging payment-provider credentials or
   network code.

## Guardrails For Future Agents

- Do not bypass `payment_gateways.py` when adding provider-specific payment
  behavior.
- Do not write AI credit ledger entries directly from provider callbacks.
- Do not let provider callback payload fields drive entitlements or credits
  without first resolving the internal payment order/refund.
- Do not make the WordPress Addon own payment details; keep it summary/link-only.
- Do not create a second AI credit billing registry outside
  `app/domain/commercial/credits.py`.
