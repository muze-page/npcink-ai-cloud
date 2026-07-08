# Admin Service Settings Alipay History - 2026-07-06

## Status

Local fix prepared on branch `codex/alipay-key-format-ui`.

This note records the Alipay service-settings debugging history and the
operational rule for future agents: fix and verify locally first, then promote
through the normal GitHub PR and production workflow.

## Scope

This work belongs to the Cloud admin commercial service-settings surface:

- `payment_alipay` service setting storage and readiness check.
- Admin UI for Alipay page-pay credentials and callback URLs.
- Payment gateway key parsing and configuration validation.

It does not change subscription state transitions, payment order state, portal
checkout behavior, WordPress control-plane ownership, or deployment secrets.

## Problems Found

### Portal base URL dependency was unclear

Alipay `notify_url` and `return_url` are derived from the configured public
portal base URL. Earlier UI behavior required saving the portal base URL before
saving Alipay settings, which produced the confusing message:

`先保存门户基础地址，再保存支付宝配置。notify_url 和 return_url 会自动生成。`

The first production fix made the page infer the current HTTPS admin origin
when safe, auto-save it as the portal base URL, then save Alipay settings.
Local `localhost` and `127.*` origins are intentionally rejected because Alipay
cannot call back to a developer machine.

### Callback URLs were too prominent

The callback base URL, notify URL, and return URL are important for copying into
the Alipay platform, but they are low-frequency details after initial setup.
Keeping all three fully visible made the page harder to scan.

The local UI fix moves callback details behind an explicit `回调地址`
disclosure. The default view keeps the current callback base visible and lets
operators expand only when they need to copy notify or return URLs.

### Key format errors exposed cryptography internals

When the operator pasted an Alipay-exported bare private key, the backend could
raise a raw cryptography error:

`Could not deserialize key data ... ASN.1 parsing error ...`

The root cause was the private-key normalization path. Bare private-key content
was always wrapped as `BEGIN PRIVATE KEY` (PKCS#8). Alipay tooling may provide
bare PKCS#1 private-key content, which needs `BEGIN RSA PRIVATE KEY`.

The local fix makes private-key loading try both PKCS#8 and PKCS#1 when the
operator pastes bare Base64 content. Public-key parsing still accepts PEM or
bare Base64 public-key content.

### Alipay public key was incorrectly treated as the app public key

The previous readiness check signed a probe with the application private key
and verified it with the configured `public_key`. That is wrong for Alipay.

In this setting:

- application private key: owned by this Cloud application; used to sign page
  pay requests;
- Alipay public key: owned by Alipay; used to verify Alipay callback
  signatures.

They are not expected to be a key pair. The readiness check now verifies that
the application private key can sign and that the Alipay public key parses as
an RSA public key. Real Alipay callback verification remains the runtime proof
that the Alipay public key is correct.

## Decisions

- Support PEM and bare Base64 key input for Alipay operator convenience.
- Keep stored secrets write-only in the UI. Existing keys remain represented as
  configured or missing, never echoed back.
- Do not require application private key and Alipay public key to match.
- Translate key parsing failures into operator-friendly Chinese copy instead of
  leaking ASN.1 or deserialization details.
- Keep callback URL details collapsed by default.
- Iterate locally first. Do not deploy every UI or validation tweak to the
  server during development.

## Local Verification

The local branch has passed:

```bash
.venv/bin/python -m pytest tests/domain/test_payment_gateways.py tests/api/test_service_routes.py::test_admin_service_settings_store_masked_cloud_runtime_config -q
node frontend/tests/unit/admin-service-settings-ui-contract.mjs
.venv/bin/python -m ruff check app/domain/commercial/payment_gateways.py tests/domain/test_payment_gateways.py
pnpm --dir frontend run type-check
pnpm --dir frontend run lint
pnpm run check:fast
git diff --check
```

Regression coverage added:

- bare PKCS#1 application private key is accepted;
- invalid key format does not expose ASN.1 or raw deserialization messages;
- application private key and Alipay public key can be distinct keys;
- callback URLs remain behind a UI disclosure.

## Release Guidance

For this class of change:

1. Fix and verify on a local branch.
2. Run the narrow backend/frontend checks first.
3. Run `pnpm run check:fast` before handoff or PR.
4. Open a normal PR to `master`.
5. Promote to `production` only after `master` checks are green and the
   production release policy is satisfied.
6. After deploy, test the production settings page with the production domain,
   not `127.0.0.1` or `localhost`.

## Operator Notes

When configuring Alipay:

- `应用私钥` should be the application private key from the merchant-side key
  generation workflow.
- `支付宝公钥` should be the Alipay platform public key, not the application
  public key.
- The two values are not supposed to match.
- If the page still reports key-format failure, first check whether a
  certificate, app public key, or the wrong field was pasted.
