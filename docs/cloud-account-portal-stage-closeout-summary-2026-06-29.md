# Cloud Account and Portal Stage Closeout Summary - 2026-06-29

Status: stage closeout summary.

Purpose: summarize the recent account, Portal, service settings, site
connection, and article-audio decisions so future operators and AI agents can
quickly understand what was decided, what was implemented, and why this stage
is considered closed.

This document is a summary of local project history. It does not introduce a
new API, a new identity type, a second WordPress control plane, or a new runtime
registry.

Historical ID note: this document records the old Free package IDs
`plan_free` / `plan_free_v1`; current package records use `free` / `free_v1`.

## Boundary

Npcink AI Cloud remains the hosted runtime and service-plane enhancement layer.
It may own runtime execution, provider configuration, service settings, usage,
entitlement evidence, account/site service state, audit evidence, and bounded
Portal/Admin surfaces.

Cloud must not become:

- a WordPress write owner;
- a second ability registry;
- a second workflow registry;
- a prompt/preset/router source of truth;
- a replacement for Core approval, preflight, execution, or audit truth;
- a customer-facing raw runtime-key console.

The external Cloud identity contract remains limited to:

- `platform_admin`: platform/operator administration.
- `user`: customer/member Portal access.

Permission differences stay as bounded actions and capability flags, not new
product identity types.

## Stage Themes

This stage covered five connected themes:

1. Account identity and login shape.
2. Platform-admin service settings migration.
3. Portal self-registration and Free package onboarding.
4. Portal site connection and key-management simplification.
5. Article-audio generation boundary and future governed adoption path.

The common decision across all five was to keep Cloud useful as a hosted service
plane while avoiding a second local WordPress control plane.

## Account And Login Decisions

### Admin and Portal remain separate

The team considered merging Admin and Portal. The accepted decision was not to
merge them in this stage.

Current shape:

- `/admin` remains the platform-admin/operator entry.
- `/portal` remains the customer/member entry.
- The two surfaces keep separate navigation and guards.
- They share the two canonical identity types, but not one mixed shell.

Reasoning:

- Admin and customer workflows have different risk models.
- A merged shell would add complexity without enough immediate value.
- Separate entry points make security and failure handling easier to reason
  about.

### QQ login is Portal-only convenience

QQ quick login is suitable for user-facing Portal login and binding. It is not
suitable as a platform-admin bootstrap, recovery, or authority path.

Current direction:

- email verification-code login remains the base Portal login path;
- QQ can be bound from the Portal account center;
- QQ binding can be revoked;
- platform-admin access remains under platform-admin session/internal-token
  controlled paths.

## Service Settings Decisions

Cloud-owned login, QQ login, and email delivery settings were migrated away from
long-term `.env` ownership toward platform-admin visual configuration and
runtime/admin storage.

Accepted rules:

- `.env` is deployment bootstrap/config, not the long-term operator settings
  surface for Portal QQ login or SMTP.
- active Cloud naming uses `NPCINK_CLOUD_*`;
- old `MAGICK_CLOUD_*` compatibility is not required because the project is
  still in development;
- operator errors should be structured JSON and shown in Chinese UI copy;
- SMTP SSL and STARTTLS should be mutually exclusive in the UI;
- when SMTP username and sender are identical, the UI can support a
  same-as-sender shortcut.

Important bug lesson:

- `Unexpected token 'I', "Internal S"... is not valid JSON` means the frontend
  tried to parse a non-JSON backend error body. Operator-facing API paths should
  return structured error envelopes, especially for service settings save/test
  failures.

Related history:

- `5b43d03 Move portal service settings to admin storage`
- `eccddd3 Add service settings import workflow`
- `e024177 Merge pull request #81 from muze-page/codex/service-settings-import-workflow`

## Portal Self-Registration And Free Package

Direct Portal self-registration was accepted.

Implemented shape:

- `POST /portal/v1/register/code/request`
- `POST /portal/v1/register/verify`

Successful registration creates:

- `Principal`
- `Account`
- `Site`
- `AccountUserMembership`
- `SiteUserGrant`
- Free subscription
- active Portal session

Important metadata:

- registration source: `portal_self_registration`
- default package: `plan_free` / `plan_free_v1`
- package alias: `Free`

The Free onboarding posture is intentionally lightweight:

- `site_limit=1`
- `300 AI credits` per period
- `max_active_runs=1`
- account/subscription entitlement snapshot is the package authority;
- Portal should show the resulting package/quota state clearly.

The stage closed with tests that verify:

- self-registration opens a Free account and Portal session;
- active entitlement snapshot exists;
- Portal entitlement view exposes the Free quota and site limit;
- repeated registration-code requests are rate-limited;
- missing registration verification payload returns structured error JSON.

Related commits:

- `89d36a1 Add portal self registration flow`
- `344e3ad Add portal account center onboarding`
- `62c9ee7 Verify portal registration readiness`

## Platform-Admin Portal User Management

Platform admins need bounded visibility and risk-reduction tools for
self-registered users. This does not make Cloud a full CRM.

Implemented shape:

- `/admin/portal-users`
- `GET /internal/service/admin/portal-users`
- `GET /internal/service/admin/portal-users/{principal_id}/audit`
- `POST /internal/service/admin/portal-users/{principal_id}/disable`
- `POST /internal/service/admin/portal-users/batch-disable`

Current capabilities:

- list self-registered users;
- filter by source, status, package, QQ binding, and query text;
- inspect account/site/package/QQ binding state;
- inspect audit detail;
- disable one user;
- lightly batch-disable users with an operator reason.

Current non-goals:

- no batch restore;
- no mixed Admin/Portal shell;
- no full CRM workflow;
- no WordPress-side write authority.

Disable semantics:

- principal status becomes disabled;
- session version increments;
- active site grants are revoked;
- active account memberships are revoked;
- QQ identity bindings are revoked;
- old Portal cookie sessions become invalid immediately.

Related commits:

- `cfd1914 Add admin portal user management`
- `871141b Add admin portal user audit detail`
- `a9c2d65 Add admin portal user batch disable`
- `62c9ee7 Verify portal registration readiness`

## Portal Site Connection And Key Management

The earlier customer-facing Portal exposed too much key-management detail. The
accepted direction is site management first, runtime credentials below the
surface.

Current product rule:

```text
Portal exposes site connection management.
Cloud service plane owns key issuance and revocation.
Addon stores runtime credentials internally for signed requests.
```

Implemented Cloud-side outcomes:

- Follow-up cleanup removed the `/portal/keys` compatibility redirect;
- Portal primary navigation no longer exposes `Keys`;
- Portal users manage sites, not raw signing credentials;
- addon connection/reconnection issues a Cloud API Key wrapper automatically;
- old active runtime keys for the same site are revoked during reconnection;
- runtime acceptance still requires an active site and active key.

Implemented addon-side outcomes, recorded in the companion repository:

- addon callback exchanges `code/state` through Cloud;
- addon saves wrapper-derived credentials internally;
- default addon settings hide Site ID, Key ID, copied key values, `mak1_...`,
  and `Bearer ...` values;
- manual recovery accepts only Cloud-issued wrappers.

UI smoke was updated to match the current Portal design:

- primary nav: Workspace, Usage, Package, Sites, Account;
- Keys is not a primary Portal entry;
- Sites keeps Add Site as a secondary action;
- Portal workspace smoke passes with this contract.

Related commits:

- `2e74e7f Add portal site activation lifecycle`
- `4f94520 Merge site activation lifecycle recovery`
- `f65db8d Replace portal site archive with remove flow`
- `d6a5fd7 Hide portal key management behind site connection`
- `e94372c Refresh portal workspace smoke contract`
- `a5eafff Document audio and site connection closeouts`

Detailed document:

- `docs/cloud-site-connection-closeout-history-2026-06-29.md`

## Article Audio Generation Boundary

Article audio was discussed as a cross-repo governed flow, not a Cloud-only
publishing feature.

Accepted first useful scope:

- article narration;
- long-form audio summary;
- editor-side candidate review;
- one article at a time;
- governed adoption through local Core/Abilities path.

Cloud may:

- execute hosted audio/text runtime work;
- call the first audio provider, MiniMax;
- store candidate artifacts according to retention policy;
- return authorized playback URLs for review;
- retain provider/model/runtime/audit evidence.

Cloud must not:

- directly mutate WordPress content;
- publish posts;
- import media as a default first-version action;
- bypass Core governance;
- become prompt/preset/account-level narration preference truth.

The governed adoption path remains:

```text
Toolbox fixed flow
-> Cloud hosted runtime candidate
-> Toolbox article_audio_adoption_plan.v1
-> Adapter submits Core proposal
-> Core policy/preflight/execution/audit
-> Abilities Toolkit writes approved metadata
-> WordPress article renders adopted playback projection
```

Detailed document:

- `docs/article-audio-generation-stage-summary-2026-06-29.md`

## Verification Completed In This Stage

Backend verification:

```bash
.venv/bin/python -m pytest tests/api/test_portal_routes.py tests/api/test_service_routes.py -q
```

Result:

- `102 passed`

Frontend smoke:

```bash
pnpm run frontend:test:e2e:portal-workspace-path
```

Result:

- `6 passed`

Frontend lint for the updated smoke:

```bash
pnpm --dir frontend exec eslint tests/e2e/portal-workspace-path.spec.ts --max-warnings=0
```

Result:

- passed

Whitespace/diff gate:

```bash
git diff --check
```

Result:

- passed

## Current Stage Conclusion

This stage is closed for product and engineering purposes.

Do not keep expanding account-management features by default. The system now
has enough for a development-stage open registration loop:

- separate Admin and Portal surfaces;
- user self-registration;
- automatic Free package;
- optional QQ binding;
- platform-admin Portal user inspection;
- single disable;
- lightweight batch disable;
- disabled-session revocation;
- Portal site-management-first navigation;
- service settings migration direction;
- recorded article-audio boundary.

The next useful work should be operational rather than more account surface:

1. run deployment/CI validation for the committed branch;
2. verify migration state in the target environment;
3. smoke real registration and service settings in a controlled environment;
4. only then decide whether to promote.

Avoid adding batch restore, merged Admin/Portal shell, richer CRM workflows,
or new WordPress-side control surfaces until there is real operator feedback
showing a concrete need.
