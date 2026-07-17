# P4 Portal/Admin Surface Inventory — 2026-07-16

## Status

Accepted inventory for P4 implementation and acceptance.

This record satisfies `P4-E01` in
`docs/refactor-deletion-inventory-v1.md`. It classifies the current customer
Portal, operator Admin, browser proxy, and shared frontend request contracts
before deletion. Historical documents remain evidence only and do not
override this inventory or the current boundary contracts.

## Scope And Fixed Boundary

- WordPress is the only current connector implementation priority.
- Cloud owns hosted execution, commercial state, Cloud identity, connection
  credentials, provider/runtime configuration, usage, entitlement, service
  audit, health, and diagnostic evidence.
- WordPress owns local abilities, workflows, prompts, presets, permissions,
  review, approval, preflight, final audit, and CMS writes.
- Portal is a bounded customer service surface. Admin is a bounded Cloud
  operator surface. Neither may become a WordPress control plane.
- There are no production users and no compatibility requirement. Removed
  routes and fields are deleted directly rather than retained as aliases.

## Authoritative Owner Map

| Displayed or operated value | Authoritative owner | Allowed surface |
| --- | --- | --- |
| Cloud principal and login binding | Cloud identity store | Portal account summary; full `principal_id` only in Admin user operations |
| Account membership and allowed customer actions | Cloud commercial identity | Server-side authorization; bounded Portal action projection |
| Site identity, URL, platform kind, and service lifecycle | Cloud site record | Portal connection/site detail; Admin customer operations |
| Runtime signing key lifecycle | Cloud service plane | Addon one-time exchange and internal operator API only; never customer self-service |
| Subscription, package, entitlement, credit, payment | Cloud commercial services | Portal billing/usage; Admin commercial operations |
| Provider connection and hosted model/runtime profile | Cloud runtime configuration | Admin runtime operations only |
| Run, callback, guard, plugin, media, vector, feedback evidence | Cloud runtime/observability stores | Portal bounded site diagnostics; Admin diagnostics |
| WordPress ability/workflow/prompt/preset/approval/apply state | WordPress/Core | Never exposed as mutable Cloud truth |
| Final WordPress content/media write and audit | WordPress/Core | Never performed by Portal/Admin |

## Portal Surface Decisions

| Surface or route family | Truth consumed | Decision | Reason / replacement |
| --- | --- | --- | --- |
| `/portal/login`, `/portal/register`, `/portal/session`, logout and account login bindings | Cloud principal/session | keep, then contract | Authentication is Cloud-owned. Customer projection must omit routine internal principal, membership, role, and account identifiers. |
| `/portal` | Session plus site/commercial/diagnostic reads | simplify | Keep a service summary. Remove per-site N+1 summary/diagnostic prefetch and account/support identity requests from the home hot path. |
| `/portal/sites` redirect | No independent truth | delete | Link directly to the retained home site list or site detail. No compatibility redirect is required. |
| `/portal/sites/{site_id}` | Cloud site, connection, health, usage, diagnostic evidence | keep | This is the bounded customer detail surface. It must not expose credentials or CMS apply controls. |
| `/portal/monitoring` redirect | No independent truth | delete | Link directly to the selected site service-status section. |
| `/portal/billing` | Cloud subscription, entitlement, credit, payment | keep | Cloud commercial truth. |
| `/portal/usage` | Cloud usage and entitlement ledgers | keep, simplify | Remove unused credit-pack/payment/ledger fan-out from bundle loading. |
| `/portal/audit` | Cloud service audit only | keep as secondary detail | It is not WordPress final audit truth and remains outside primary navigation. |
| `/portal/support` and request detail | Cloud support records | keep | Customer support is Cloud-owned; attachment bodies remain bounded and authorized. |
| `/portal/account` | Cloud email/session/QQ binding | keep, contract | Do not display or infer internal principal/account/role identifiers. |
| `POST /portal/v1/sites` | Portal-created Cloud site | delete now | The UI path is dead. New WordPress sites connect through the addon flow. |
| Portal site activate/deactivate routes | Cloud site lifecycle | delete now | No frontend consumer; connection and remove flows provide the retained lifecycle. Internal operator routes remain. |
| Portal site API-key list/create/rotate/revoke | Cloud signing credentials | delete now | Users manage sites, not keys. Addon connection automatically reissues a hidden key through one-time exchange. |
| Portal addon connection and exchange | Cloud site connection plus hidden signing credential | keep and harden | Existing active account membership with `provision_sites` authority is a precondition. A connection never creates membership. |
| Portal site remove | Cloud site lifecycle | keep | Requires existing site access and removal authority; revokes active keys and preserves evidence. |
| Portal AI insight history/analyze | Hosted diagnostic runtime | keep backend, remove dormant client methods | This is suggestion/diagnostic evidence, not CMS approval or write truth. |
| Dormant analytics client methods | No matching backend route | delete | They are dead client claims, not a supported contract. |

## Admin Surface Decisions

| Surface or route family | Truth consumed | Decision | Reason / replacement |
| --- | --- | --- | --- |
| Admin session and browser API proxy | Platform-admin session and internal service APIs | harden now | Require platform-admin identity/role, explicit capability, and a method/path/namespace allowlist before adding the internal token. Unknown routes fail closed. |
| `/admin` overview | Multiple Cloud service summaries | keep, simplify later | Retain conclusions and action queues; move deep evidence to dedicated pages and remove unbounded usage/credit loading. |
| Customers: accounts, account/site detail, Portal users, support | Cloud identity/commercial/support | keep | These are platform operations. Full stable `principal_id` is allowed for Admin support and audit. |
| Commercial: coverage, subscriptions, plans, credit packs | Cloud commercial truth | keep | Cloud owns service packages, entitlement and billing operations. |
| Runtime: provider/model resources, external services, vector settings | Cloud runtime configuration | keep | Provider secrets remain write-only and getters expose configuration status, never secret material. |
| `/admin/ability-models` | Cloud hosted runtime profile binding mixed with WordPress-oriented copy | replace later in P4 | Rename/reframe as runtime profiles. Retain Cloud execution profile binding; remove local ability/workflow/prompt/preset implications. |
| `POST /admin/ability-models/runtime-binding` | Constant 409 historical stub | delete later in P4 | It has no behavior and must be removed with the runtime-profile UI cutover. |
| Audio preview inside ability-model workspace | Provider diagnostic experiment | move or delete later | If retained, place under provider diagnostics; it is not ability truth. |
| Diagnostics: troubleshooting, plugin/media/vector observability, agent feedback | Cloud runtime evidence | keep | Read/diagnostic ownership is correct. |
| Operations advisor | Cloud diagnostic summaries | keep advanced, simplify later | It cannot mutate provider, package, routing, WordPress, or approval state. |
| Service settings | Cloud Portal/email/payment configuration | keep | Platform-admin-only Cloud configuration. Secrets remain write-only. |
| Read-only agent workflow metadata | Bounded Cloud projection | keep read-only | Mutation or local workflow ownership remains forbidden. |
| Retention cleanup and other internal-only operations | Cloud production operations | deny from catch-all | A future internal route must never become browser-accessible by default. |

## Shared Frontend Contract Decisions

| Current implementation | Decision | Required end state |
| --- | --- | --- |
| Unused `cloud-client.ts` plus permissive `envelope.ts` | delete now | One strict `ApiClient` and `ApiError`. |
| `portal-client.ts` with its own envelope/error and dormant Admin/key/analytics methods | contract later in P4 | Keep a Portal domain facade only; use the shared transport and remove dead methods/types. |
| Raw Admin `fetch` implementations | migrate by page batches | All Admin pages use the shared transport/error evidence model without touching proxy ownership. |
| BFF error responses with top-level `revision` | delete shape now | Canonical `status/error_code/message/data/meta{trace_id,revision}` envelope. |
| Portal session nested `site`, `sites[].site`, `accounts[].sites` compatibility | delete in one backend/frontend cutover | One flat site projection and one selected account/site context. |

## Security Findings And Required Proof

### Portal account authorization

Before P4, `POST /portal/v1/sites` and `POST /portal/v1/addon-connections`
accepted a client `account_id`, verified only that the account and principal
were independently active, then created an account membership. This allowed a
known foreign account identifier to become an authorization input.

Required proof:

- account, principal, and existing membership are active before any write;
- `provision_sites` is explicitly present;
- a denied request creates no membership, site, key, or connection state;
- connection and site provisioning never grant membership;
- cross-account and missing-action tests return the same bounded 403 error.

### Admin internal-service proxy

Before P4, unmatched Admin browser routes defaulted to an internal-service path
and received the internal token. A future internal endpoint could therefore be
exposed without an explicit browser decision.

Required proof:

- only declared method/path pairs resolve;
- every rule names its backend namespace and current session capability;
- platform-admin identity and role are mandatory;
- unknown and dangerous retention paths fail before token injection;
- Portal-only debug headers are not forwarded;
- proxy-generated errors use the canonical envelope and do not expose internal
  network exception text.

## Implementation Batches

1. **P4-A Admin proxy security:** explicit allowlist, identity/capability gate,
   canonical errors, and focused contracts.
2. **P4-B Portal account authorization:** membership/action check at the domain
   boundary with zero-side-effect cross-account tests.
3. **P4-C Portal legacy deletion:** remove manual site lifecycle and customer
   key routes while preserving internal service and addon exchange paths.
4. **P4-D Shared client foundation:** one strict envelope, transport, error,
   and idempotency contract.
5. **P4-E Portal performance and identity projection:** remove home N+1,
   dormant client methods, aliases, and multi-account first-item fallbacks.
6. **P4-F Admin runtime-profile and page-client contraction:** reframe the
   ability-model surface and migrate Admin page batches to the shared client.

## Gates

- Focused Admin proxy and frontend transport tests.
- Portal cross-account, removed-surface, addon exchange, and authorization
  tests.
- Frontend contract suite, type-check, and lint.
- `pnpm run check:fast`.
- `pnpm run check:seam`.
- `pnpm run check:perimeter`.
- `pnpm run check:anti-drift`.
- Read-only browser smoke and screenshots for retained Portal/Admin surfaces
  before P4 closeout.

## Non-Goals

- No WordPress plugin changes in this batch.
- No Typecho, Z-BlogPHP, Ghost, MCP-channel, or OpenClaw implementation.
- No production deployment or cleanup enablement.
- No deletion of internal service-plane key lifecycle, provider management,
  commercial operations, or diagnostic evidence.
- No attempt to build a universal CMS content model.

## Implementation Evidence — 2026-07-16

This milestone implements the fail-closed and high-return contraction batches;
it is not the complete P4 closeout.

Implemented:

- Admin browser routing now requires platform-admin identity/role, an existing
  explicit capability, and a method/path/namespace allowlist before the
  internal token is added. The four exact Advisor BFF routes enforce the same
  diagnostic capability. Unknown routes and retention cleanup fail closed.
- Admin session projection uses canonical `principal_id` only; the
  `platform_admin_ref` compatibility alias is deleted and capability parsing
  accepts only the literal boolean `true`.
- Portal addon connection requires an existing active account membership with
  `provision_sites` before any site, key, or connection-state write. Connection
  no longer creates membership. Cross-account and missing-action failures have
  zero side effects.
- Manual Portal site creation, Portal activate/deactivate, and customer key
  CRUD are deleted. Internal key operations and addon one-time exchange remain.
- Portal home no longer performs per-site summary/diagnostic prefetch or home
  identity/support requests. It uses the session projection plus one account
  entitlement request, reducing the audited worst case from 16 extra requests
  to one.
- `/portal/sites` and `/portal/monitoring` redirect pages are deleted. All
  retained links target `/portal#sites` or a site detail service-status anchor.
- Frontend data access now has one strict `ApiClient`, one canonical envelope,
  and one evidence-rich `ApiError`. The unused Cloud client/envelope, Portal
  key/manual/Admin/Analytics methods, token compatibility, and no-op auth option
  are deleted. `PortalClient` contracts from 3,027 lines / 82 async methods to
  2,322 lines / 63 async methods.

Final gates on the integrated working tree:

- frontend contracts, type-check, and lint: passed;
- frontend Vitest: 13 passed;
- Portal Playwright workspace: 8 passed;
- Portal login/addon Playwright: 5 passed;
- Admin operator Playwright: 9 passed;
- `pnpm run check:fast`: 145 contract passed, 1 skipped; 597 domain passed,
  3 skipped;
- `pnpm run check:seam`: 706 API passed; perimeter 9 passed;
- `pnpm run check:anti-drift`: passed;
- Python Ruff and mypy: passed, 227 source files checked by mypy.

Still required before declaring P4 complete:

- replace the customer session's routine `principal_id/account_id/role`, nested
  account/site compatibility fields, and `site_admin_ref/member_ref` guesses
  with one bounded projection;
- derive multi-account commercial scope from an explicitly authorized selected
  site/account context and fail closed when ambiguous; never select the first
  storage result;
- migrate the remaining raw Admin page fetches to the shared client in bounded
  page batches;
- replace `/admin/ability-models` with the Cloud-owned runtime-profile surface,
  delete the constant-409 binding stub, and move or delete audio preview;
- simplify the Admin overview and operations advisor hot paths;
- complete `P4-E03` read-only retained-surface screenshot evidence after those
  remaining UI contracts land.
