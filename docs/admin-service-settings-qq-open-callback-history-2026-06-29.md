# Admin Service Settings QQ and Open Callback History - 2026-06-29

## Status

Accepted implementation history.

This document summarizes the local discussion and implementation history for
QQ quick login, the public `/open` callback namespace, and the
`/admin/service-settings` operator UI.

It is a local history record for future operators and AI agents. The normative
callback contract remains in
[`cloud-open-callback-boundary-v1.md`](cloud-open-callback-boundary-v1.md).

## Boundary

Npcink AI Cloud remains the hosted runtime and service-plane enhancement layer.
This work does not introduce:

- a second WordPress control plane;
- a local ability, workflow, prompt, router, MCP, or OpenClaw truth;
- Cloud-side WordPress write authority;
- payment truth without provider signature verification;
- a general anonymous public API under `/open`.

The `/open` namespace is only for provider callbacks that must be reachable
from external identity and payment platforms.

## Problem Context

The operator needed to configure QQ quick login from:

```text
http://127.0.0.1:8010/admin/service-settings
```

The production Cloud deployment location is:

```text
https://cloud.npc.ink
```

The initial question was whether a single callback base such as
`https://cloud.npc.ink/open` could be shared by QQ login, WeChat login, Alipay
payment, and WeChat Pay.

The accepted answer was yes, but only as a namespace prefix. Each provider and
callback purpose should still have a provider-specific path.

## Accepted Public Callback Paths

The accepted public callback path contract is:

```text
/open/auth/qq/callback
/open/auth/wechat/callback
/open/payments/alipay/notify
/open/payments/alipay/return
/open/payments/wechat/notify
```

Production examples:

```text
https://cloud.npc.ink/open/auth/qq/callback
https://cloud.npc.ink/open/auth/wechat/callback
https://cloud.npc.ink/open/payments/alipay/notify
https://cloud.npc.ink/open/payments/alipay/return
https://cloud.npc.ink/open/payments/wechat/notify
```

Reasoning:

- `/open` makes the public provider-callback surface explicit.
- Provider-specific paths prevent login and payment callbacks from being
  conflated.
- Payment `notify` and browser `return` are separate concepts.
- WeChat login and payment callbacks can be reserved now, but must fail closed
  until provider validation is implemented.

## QQ Connect Operator Guidance

For the current Cloud Portal login model, the safest QQ Connect configuration
is:

```text
Website URL: https://cloud.npc.ink
Callback domain/path: https://cloud.npc.ink/open/auth/qq/callback
```

During the discussion, the operator asked whether QQ Connect requires the
website address and callback host to be exactly the same site. The working
finding was:

- no explicit official rule was found requiring the website URL and callback
  URL to be the exact same host string;
- the callback must be under the registered application domain and match the
  callback value configured in QQ Connect;
- to reduce review risk, use `https://cloud.npc.ink` as the website URL when
  QQ login is for the Cloud Portal hosted at `cloud.npc.ink`;
- avoid mixing `https://www.npc.ink` as the website URL with
  `https://cloud.npc.ink/...` callbacks unless there is a clear product reason
  and the QQ Connect application review accepts that relationship.

This is an operator guidance note, not a permanent legal or platform-policy
guarantee. Re-check the QQ Connect console and official review guidance before
production submission if their rules change.

## Backend Implementation History

Commit:

```text
c751f67 Normalize public open callback routes
```

Implemented shape:

- added `app/api/routes/open.py`;
- registered the public `/open` router in `app/api/main.py`;
- made `GET /open/auth/qq/callback` delegate to the existing Portal QQ login
  completion flow;
- reserved these paths as fail-closed placeholders:
  - `GET /open/auth/wechat/callback`;
  - `POST /open/payments/alipay/notify`;
  - `GET /open/payments/alipay/return`;
  - `POST /open/payments/wechat/notify`;
- changed the QQ default callback to `/open/auth/qq/callback`;
- temporarily kept legacy `/portal/v1/auth/qq/callback` compatibility;
- widened the QQ nonce cookie path so the new callback can read and clear the
  login nonce;
- added `/open/` proxy support to development and production Nginx configs;
- added `docs/cloud-open-callback-boundary-v1.md`;
- updated backend and deployment contract tests.

Verification used during that implementation:

```bash
.venv/bin/python -m pytest \
  tests/api/test_service_routes.py::test_admin_service_settings_store_masked_cloud_runtime_config \
  tests/api/test_service_routes.py::test_admin_service_settings_reject_qq_redirect_outside_public_base \
  tests/api/test_service_routes.py::test_admin_service_settings_allow_legacy_qq_redirect_path

.venv/bin/python -m pytest \
  tests/api/test_portal_routes.py::test_portal_qq_bind_and_callback_login_reuse_user_session \
  tests/api/test_portal_routes.py::test_portal_qq_callback_bind_intent_binds_current_session \
  tests/api/test_portal_routes.py::test_open_reserved_callbacks_fail_closed \
  tests/api/test_portal_routes.py::test_portal_qq_callback_requires_existing_binding
```

## Admin UI Decision History

The initial admin UI exposed too many routine QQ OAuth fields:

- callback URL;
- scope;
- timeout seconds.

The accepted simplification was:

- keep the public base URL editable because local, staging, and production
  environments differ;
- generate the QQ callback URL from the public base URL;
- make the generated QQ callback URL read-only and copyable;
- fix `scope` to `get_user_info`;
- fix timeout to `10` seconds;
- use switches for enable controls instead of checkboxes;
- keep the Portal base URL setting and QQ login setting as separate save
  operations because they are separate backend service settings.

Commit:

```text
3d54073 Simplify service settings QQ login UI
```

Current UI intent:

- `门户基础地址`: owns the Cloud public base URL used to derive public
  callbacks;
- `门户入口启用`: controls whether that public Portal base is active;
- `保存基础地址`: saves only the public base URL setting;
- `QQ 快捷登录`: owns QQ App credentials and the QQ login enable switch;
- `启用 QQ 登录`: controls QQ login only;
- `保存 QQ 配置`: saves only the QQ login setting;
- `检查 QQ 配置`: validates the QQ login configuration.

The UI also explains:

```text
回调地址由门户基础地址自动生成；这里仅保存 QQ App 凭据和登录开关。
```

This prevents the two independent enable/save controls from looking like
duplicated actions.

Verification used for the UI change:

```bash
node tests/unit/admin-service-settings-ui-contract.mjs
pnpm run type-check
```

The UI contract now prevents routine re-exposure of QQ `scope` and
`timeout_seconds`, and checks that the Portal base URL and QQ login sections use
distinct action labels.

## Current Operator Setup

For production Cloud at:

```text
https://cloud.npc.ink
```

set the admin service settings as:

```text
门户基础地址: https://cloud.npc.ink
门户入口启用: on
QQ App ID: value from QQ Connect
QQ App Secret: value from QQ Connect
启用 QQ 登录: on after QQ review/config is ready
```

The generated QQ callback should be:

```text
https://cloud.npc.ink/open/auth/qq/callback
```

For local development at:

```text
http://127.0.0.1:8010
```

the generated callback is:

```text
http://127.0.0.1:8010/open/auth/qq/callback
```

External providers normally cannot call a loopback callback, so local callback
testing still needs an externally reachable tunnel or provider-side test mode.

## Remaining Follow-Ups

Do not treat reserved callbacks as implemented product features.

Before enabling each provider in production:

- WeChat login needs provider configuration, state validation, account-binding
  behavior, and tests.
- Alipay notify needs signature verification, idempotency, order identity and
  amount checks, and audit evidence before changing commercial state.
- Alipay return must remain browser return UX, not payment truth.
- WeChat Pay notify needs signature verification and reconciliation before
  any subscription or entitlement change.
- Legacy `/portal/v1/auth/qq/callback` should be removed after development and
  deployed configurations have migrated to `/open/auth/qq/callback`.

## Related Files

- `app/api/routes/open.py`
- `app/api/routes/portal.py`
- `app/domain/service_settings.py`
- `app/api/main.py`
- `deploy/nginx.dev.conf`
- `deploy/nginx.prod.conf`
- `docs/cloud-open-callback-boundary-v1.md`
- `frontend/src/app/admin/service-settings/page.tsx`
- `frontend/tests/unit/admin-service-settings-ui-contract.mjs`
- `tests/api/test_portal_routes.py`
- `tests/api/test_service_routes.py`
- `tests/contract/test_deploy_config_contract.py`
