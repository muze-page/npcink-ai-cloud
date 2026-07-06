# Admin and Portal User Management History - 2026-06-29

## Status

Accepted implementation history.

This document summarizes the recent account, login, service settings, and
Portal user-management decisions for `npcink-ai-cloud`. It is a local history
record for future operators and AI agents. It does not introduce a new control
plane, a new identity type, or a WordPress write owner.

## Boundary

Npcink AI Cloud remains the hosted runtime and service-plane enhancement layer.
WordPress/plugin-side systems remain the control plane for local abilities,
workflows, approval, preflight, and final WordPress writes.

The Cloud identity contract remains limited to:

- `platform_admin`: bounded Cloud operator/admin surface.
- `user`: bounded Portal member/account/site surface.

Permission differences should stay as bounded capabilities and actions. They
should not become new product-layer identity types.

## Decisions Made

### QQ Login

QQ quick login is suitable for the user-facing Portal, not for replacing the
platform-admin login model.

The accepted direction was:

- keep QQ as an optional Portal identity provider;
- allow existing Portal users to bind QQ from account center;
- keep email verification-code login as the base user login path;
- do not use QQ as a platform-admin bootstrap or recovery mechanism.

Reasoning:

- QQ login improves customer convenience after self-registration.
- Admin access is higher risk and should remain under platform-admin session
  and internal-token-controlled paths.
- QQ binding must be revocable and should not become the primary authority for
  Cloud account ownership.

### Admin and Portal Entry Points

`/admin` and `/portal` remain separate entry points, navigation trees, and auth
guards.

The team explicitly considered merging admin and Portal, but deferred it.

Accepted direction:

- keep `/admin` for platform-admin/operator work;
- keep `/portal` for customer/member workspace;
- do not merge the login entry points in the current phase;
- do not create a mixed admin/user shell.

Reasoning:

- Separate entry points keep the risk model clear.
- Platform-admin workflows and customer workflows have different failure modes.
- Merging now would add complexity without enough product value.
- The codebase is still in active development, but simple boundaries are still
  valuable.

### Service Settings Migration

Cloud-owned login, QQ login, and email delivery settings were moved toward
Cloud runtime/admin storage rather than long-term `.env` ownership.

Accepted direction:

- service configuration should be visible and editable from the platform-admin
  service settings page;
- `.env` remains deployment bootstrap/config only, not the long-term operator
  settings surface for QQ and SMTP;
- legacy `MAGICK_CLOUD_*` naming should not remain in active config paths;
- new active naming should use `NPCINK_CLOUD_*`;
- because the project is still in development, compatibility with old
  `MAGICK_CLOUD_*` env names is not required.

Related implementation history:

- `5b43d03 Move portal service settings to admin storage`
- `eccddd3 Add service settings import workflow`
- `e024177 Merge pull request #81 from muze-page/codex/service-settings-import-workflow`

Operator-facing bug notes from the same discussion:

- `Unexpected token 'I', "Internal S"... is not valid JSON` happened because
  the frontend tried to parse a non-JSON backend error body as JSON.
- SMTP save/test failures should show Chinese, structured operator errors and
  should distinguish database migration/configuration failures from SMTP
  provider authentication failures.
- SMTP SSL and STARTTLS are mutually exclusive. If both are selected, the UI
  should prevent or explain the invalid state.
- SMTP username can use a same-as-from-email shortcut when the two values are
  identical.

### Self-Registration

Direct user self-registration is accepted for the Portal.

Accepted direction:

- allow a new user to request a registration code;
- verify the code through Portal;
- automatically create a principal, account, site, membership, grant, and Free
  subscription;
- keep source metadata as `portal_self_registration`;
- issue a Portal session after successful registration;
- offer QQ binding from account center after registration.

Reasoning:

- The project needs a convenient first-user path.
- Free plan auto-opening reduces onboarding friction.
- The service-plane can still suspend, disable, or revoke access when abuse
  appears.
- Registration remains bounded to Cloud account/site/service state and does not
  create WordPress write authority.

Related implementation history:

- `89d36a1 Add portal self registration flow`
- `344e3ad Add portal account center onboarding`

### Platform-Admin User Management

Platform-admin needs visibility into self-registered Portal users, but this
should remain a bounded service-plane management surface.

Accepted direction:

- add `/admin/portal-users` as a separate admin page;
- list self-registered Portal users with account, site, package, status, and
  QQ binding state;
- allow single-user disable;
- expose user audit details;
- allow lightweight batch disable;
- do not implement batch restore yet.

Reasoning:

- Admins need to inspect and stop abusive or invalid self-registered accounts.
- Disable is a risk-reducing action: it removes access.
- Restore is more complex and can accidentally re-grant access across account,
  site, and identity-provider boundaries. It should remain manual or be designed
  later from explicit audit snapshots.

Related implementation history:

- `cfd1914 Add admin portal user management`
- `871141b Add admin portal user audit detail`
- `a9c2d65 Add admin portal user batch disable`

## Current Implemented Shape

### Portal self-registration

Current API shape includes:

- `POST /portal/v1/register/code/request`
- `POST /portal/v1/register/verify`

Successful verification creates:

- `Principal`
- `Account`
- `Site`
- `AccountUserMembership`
- `SiteUserGrant`
- Free subscription
- Portal session

Important source metadata:

- `portal_self_registration`

### Portal account center

Current Portal account center supports:

- viewing identity-provider state;
- starting QQ bind flow with bind intent;
- unbinding QQ login.

QQ binding remains a Portal user convenience. It is not an admin login source.

### Admin Portal user list

Current internal API:

- `GET /internal/service/admin/portal-users`

Supported filters include:

- `q`
- `source`
- `status`
- `package_alias`
- `qq_bound`
- `limit`

The frontend page is:

- `/admin/portal-users`

The page shows:

- principal/email/status;
- registration source;
- account and membership status;
- site and grant status;
- package/subscription;
- QQ binding state;
- created and last-login timestamps.

### Single-user disable

Current internal API:

- `POST /internal/service/admin/portal-users/{principal_id}/disable`

Disable behavior:

- sets `Principal.status` to `disabled`;
- increments `Principal.session_version`;
- revokes active site grants;
- revokes active account memberships;
- revokes active QQ identity-provider bindings;
- records `portal_user.disable` service audit evidence.

### Audit detail

Current internal API:

- `GET /internal/service/admin/portal-users/{principal_id}/audit`

The audit view reads existing `ServiceAuditEvent` data. It does not create a
second audit truth.

It shows:

- principal identity summary;
- registration event count;
- disable event count;
- latest disable reason;
- revoked grant/membership/QQ-binding counts;
- event actor, path, trace id, idempotency key, scope, and time.

### Lightweight batch disable

Current internal API:

- `POST /internal/service/admin/portal-users/batch-disable`

Batch disable behavior:

- accepts up to 100 principal IDs;
- requires a reason;
- de-duplicates principal IDs;
- processes each principal independently;
- missing principals return failed item results but do not stop the batch;
- writes one `portal_user.disable` audit event per successfully processed user;
- writes one `portal_user.batch_disable` summary audit event.

The frontend page supports selecting active users in the current list and
submitting a required reason.

Batch restore is intentionally not implemented.

## Security Notes

The current design improves safety by keeping the most dangerous actions
one-way in the short term:

- disable and revoke are supported;
- restore is not automated;
- QQ binding is revoked on disable;
- session version increments invalidate active sessions;
- batch disable requires an idempotency key through the admin proxy and a human
  reason in the payload;
- audit events record the action evidence.

Security risks to keep in mind:

- Self-registration can attract abuse; rate limits, content-risk rules, and
  domain/site review remain important follow-ups.
- Batch disable is intentionally capped to avoid accidental large-impact
  operations.
- Any future restore flow must prove that the account, site, membership, grant,
  and identity-provider state are safe to re-enable.

## Performance Notes

The current user management implementation is acceptable for the development
stage, but it uses read-model aggregation over principals, memberships, grants,
sites, accounts, subscriptions, and identity-provider bindings.

Before large-scale production use, consider:

- pagination/cursor-based list loading;
- indexes for principal-source and audit lookup if needed;
- a dedicated read model only if measured list latency requires it;
- tighter query filters before loading related rows.

Do not add read-model infrastructure preemptively.

## Explicit Non-Goals

These were intentionally not implemented:

- merging `/admin` and `/portal`;
- using QQ as platform-admin authentication;
- batch restore;
- checkout/payment front-office;
- WordPress publishing or write control from Cloud;
- second ability registry;
- second workflow registry;
- prompt/router/preset control plane.

## Suggested Next Steps

Recommended near-term sequence:

1. Keep the new Admin Portal user management surface stable and use it in local
   operator smoke tests.
2. Add targeted abuse/risk filters only after real evidence appears.
3. If restore becomes necessary, design it as a single-user, audit-snapshot
   based restore path first.
4. Add pagination only when user count or measured latency justifies it.
5. Keep all account/user actions in service-plane audit.

## Verification History

The relevant changes were verified with targeted checks during implementation:

- `uv run pytest tests/api/test_service_routes.py::test_admin_portal_users_lists_self_registered_users_and_disables_access -q`
- `uv run pytest tests/api/test_service_routes.py::test_admin_portal_users_batch_disable_processes_each_principal -q`
- `uv run ruff check ...`
- `node tests/unit/admin-portal-users-ui-contract.mjs`
- `pnpm run frontend:type-check`
- `pnpm run frontend:lint`
- `git diff --check`

