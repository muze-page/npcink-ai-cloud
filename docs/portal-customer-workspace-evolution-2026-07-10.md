# Portal Customer Workspace Evolution - 2026-07-10

Status: accepted stage summary with follow-up work.

Purpose: consolidate the recent Portal product discussions, implemented changes,
root-cause lessons, and next-stage engineering direction into one local record.
This document explains why the Portal was simplified and how future work should
continue. It does not introduce a new API or database contract.

## Related Records

This summary builds on the more focused historical records below:

- `docs/portal-customer-surface-simplification-history-2026-07-04.md`
- `docs/portal-auth-verification-closeout-2026-07-08.md`
- `docs/cloud-account-portal-stage-closeout-summary-2026-06-29.md`
- `docs/cloud-site-connection-closeout-history-2026-06-29.md`
- `docs/admin-portal-user-management-history-2026-06-29.md`

When details conflict, the current code, migrations, tests, and newer boundary
contracts take precedence over these historical summaries.

## Product Boundary

The Portal is a bounded customer service center for Cloud account information
and service evidence. It may expose:

- account package and entitlement detail;
- account-scoped usage and billing records;
- connected WordPress site records and connection lifecycle actions;
- customer support requests, replies, attachments, and feedback;
- customer-readable service status and recent activity.

The Portal is not a second WordPress control plane. It must not own local
abilities, workflows, prompts, presets, approval, preflight, final WordPress
writes, or local plugin configuration truth. The WordPress addon remains the
connection initiator and thin runtime client. Cloud remains the hosted runtime,
commercial evidence, connection credential, and support-detail owner.

## Core Product Model

The discussions converged on one simple customer model:

```text
Customer account
  -> package, entitlement, usage, billing, support
  -> one or more connected site records

WordPress site
  -> connection status, address, connected time, runtime credential lifecycle
```

Package, usage, billing, and support are account/customer concerns. A site is a
connected service endpoint and attribution record; it is not the owner of the
customer package. This distinction drove the removal of the global site switch
from normal Portal navigation and the removal of package information from site
cards.

Site-scoped URLs and explicit `site_id` values still exist where an operation
really targets one site. Removing the global selector does not mean erasing
site identity from runtime, usage attribution, audit evidence, or site detail
routes.

## Historical Problems And Decisions

### 1. Site management exposed implementation details

Earlier Portal and addon surfaces exposed too much connection machinery:

- raw key-management concepts;
- Site ID and Key ID values;
- repeated customer/account context in the binding modal;
- editable WordPress URL fields even when the addon had already supplied the
  canonical URL;
- support/debug disclosures inside the primary connection flow.

The accepted direction is task-oriented site management:

- WordPress starts a connection from the addon;
- Portal confirms the supplied site and display name;
- Cloud issues or rotates the runtime credential below the customer surface;
- the addon stores the returned wrapper-derived credential internally;
- Portal lets the customer inspect, disable, reconnect, or remove a site;
- removing a site archives service history and revokes active runtime keys
  instead of deleting usage or audit evidence.

Binding UI should show only information needed to make the immediate decision.
Account context, repeated URL inputs, and generic support disclosures do not
belong in that confirmation step unless they resolve a real ambiguity.

### 2. Site lifecycle and connection errors were mixed together

The error
`site 'site_magick-ai-local' is not available for addon connection
[service.portal_site_not_connectable]` represented a lifecycle/ownership
conflict, not a generic login failure. A site can be unavailable because it is
already connected under an incompatible state, belongs to another account, is
suspended, or cannot be reactivated through the requested path.

The engineering rule is to resolve connection eligibility from explicit
account ownership and site lifecycle state. Do not infer connection authority
from whichever site happened to be selected in a session. Errors should name
the actionable reason where it is safe to do so, while preserving account and
site enumeration protections.

### 3. Login state, account membership, and selected site were conflated

Being authenticated proves the browser owns a valid Portal session. It does not
by itself prove that the principal has an active customer-account membership.
Historical data allowed three records to drift apart:

- `Principal`: login identity;
- `AccountUserMembership`: customer-account access;
- `SiteUserGrant`: per-site access record.

Compatibility code previously treated an active site grant as sufficient Portal
access and automatically selected the first active site. That produced confusing
states such as "logged in, but no customer account" and made addon binding
depend on an unrelated current-site fallback.

The accepted current rule is:

- an active `AccountUserMembership` is required for Portal account access;
- a site grant alone is not a login or account-membership substitute;
- Portal session serialization does not silently select the first active site;
- addon binding receives account context directly;
- account context must not be reconstructed from the first visible site;
- missing membership is reported as a missing/inactive customer account, not as
  an instruction to switch to another site.

This removed the historical compatibility path from login and session
selection. It did not yet remove `SiteUserGrant` from every site-detail access
check; that remaining dual-authority model is tracked under follow-up work.

### 4. Local development used two different cookie hosts

`localhost` and `127.0.0.1` can reach the same local service, but browser cookies
are host-bound. A session created at
`http://127.0.0.1:8010/portal/dev-entry` is not automatically available to
`http://localhost:8010/portal/sites`.

The local-development rule is to use one canonical host through the complete
login and addon-binding flow. Login redirects must preserve the full path and
query string, including `connect`, `site_url`, `site_name`, `return_url`, and
`state`. Preserving the query fixes callback continuity; it does not make cookies
portable between hostnames.

### 5. Package, usage, and billing repeated the same information

The customer pages previously mixed package rights, site state, usage counters,
technical records, and payment details. The accepted separation is:

- Package answers: "What does my account include?"
- Usage answers: "What did my account use during this period?"
- Billing answers: "What did I order or pay for?"
- Sites answers: "Which WordPress sites are connected?"

Applied UI rules include:

- keep the main entitlement summaries in one responsive row when space allows;
- show the entitlement period near the summary because time defines the quota;
- keep package records behind a secondary disclosure when they are mainly
  useful for support;
- remove repeated validity copy from every credit-pack card when the section
  already states the same rule;
- use translated customer-facing names and statuses;
- use CNY and the `¥` symbol consistently for the current commercial catalog;
- automatically cancel stale unpaid payment orders after the bounded expiry
  window instead of leaving them permanently in "waiting for confirmation";
- keep historical package and payment records only when they explain service
  state, reconciliation, or support decisions.

### 6. Generic help copy was replaced by an actual support workflow

Static "contact support" copy at the bottom of pages did not give the customer
an actionable path or give operators a trackable record. The accepted solution
was a first-class Support tab connected to the Admin support queue.

The implemented support flow includes:

- customer request creation and list/detail views;
- Admin request queue and operator detail view;
- customer/operator message replies;
- public and internal message visibility boundaries;
- bounded attachments;
- resolved/closed lifecycle;
- customer feedback and rating after resolution or closure.

Support remains account/customer scoped. Site context may be attached to a
request when relevant, but selecting a global current site is not required to
open or follow a support request.

### 7. Global site selection did not match the customer workspace

The old header selector implied that Package, Usage, Billing, and Support all
changed with the selected site. That contradicted their actual account-scoped
data model and created unnecessary search/dropdown UI for single-site users.

The selector was removed from the normal Portal shell. Site navigation now
happens through the Sites page and explicit site-detail routes. Site identity
remains available only where it changes the result, such as a site record,
site-specific service status, or usage attribution filter.

### 8. Site pages contained explanatory and summary clutter

The site list accumulated repeated helper text, connection instructions, a
"current site" summary, and an oversized connected-time block. The accepted
layout principles are:

- remove text that merely narrates visible UI;
- show connection instructions in the empty state or addon connection flow,
  not as a permanent banner above every site;
- place connected time in compact row metadata because it is important but not
  the primary action;
- keep site count and attention state only when they help scanning;
- keep search only when the account has enough sites for it to be useful;
- use clear `View site` and `Remove site` actions without duplicating site data.

### 9. Customer UI should prefer decisions over diagnostics

Across all Portal pages, the recurring simplification rule is:

- show status first;
- show one clear action for the current task;
- use plain customer language;
- remove internal IDs, permission scopes, provider/runtime terminology, and
  duplicate explanations;
- move support evidence behind detail views;
- avoid cards inside cards and avoid using large cards for ordinary page
  sections.

## Current Authorization Shape

As of this summary, Portal authorization is intentionally moving toward one
account-level truth, but the transition is not fully complete.

| Record | Current responsibility | Direction |
| --- | --- | --- |
| `Principal` | Authentication identity and session version | Keep |
| `AccountUserMembership` | Active customer-account access and Portal actions | Canonical Portal authority |
| `SiteUserGrant` | Additional site-detail access check and historical admin evidence | Retire if no independent site ACL is required |
| Portal session `account_id` | Current account context | Keep explicit |
| Portal session `site_id` | Optional explicit site context | Do not auto-select |

The product discussions did not identify a customer requirement for a user to
see only selected sites inside an account. Unless such a requirement appears,
maintaining both account membership and site grants creates two authorization
truths and risks a visible inconsistency: an account member can see a site in an
account-level list but receive `403` when opening its detail page.

## Development Principles Derived From This Stage

1. Start from the customer-owned object. Package, usage, billing, and support
   start from account membership; site operations start from an explicit site.
2. Do not use UI state as authorization evidence. A selected site, visible card,
   or query parameter never substitutes for backend membership checks.
3. Remove compatibility paths when the product model has changed. Silent
   fallback keeps contradictory truths alive and makes failures harder to
   explain.
4. Preserve lifecycle evidence instead of deleting history. Archive sites,
   cancel expired orders, revoke credentials, and retain audit attribution.
5. Keep connection credentials below the customer surface. Users manage a
   connection outcome, while Cloud and the addon manage signing material.
6. Make local auth flows deterministic. Use one hostname, preserve the full
   redirect, and test cookie-backed navigation in a browser.
7. Let tests express the product rule. Contract tests should reject the old
   fallback, not merely verify the new copy.
8. Keep Cloud bounded. Portal can manage Cloud service records and support
   detail, but it must not become a WordPress write or local-governance owner.

## Implemented Milestones

Representative commits from this stage include:

- `519ab0e1 Improve portal payment and site lifecycle flows`
- `0c48862f Add portal support request queue`
- `834eeb8f Add support request message replies`
- `0dbe43e3 Add support request attachments and feedback`
- `69965903 Make portal usage and audit account scoped`
- `2c445fe3 Enforce CNY commercial pricing`
- `7b371108 Simplify portal customer workspace`
- `ed338a6b Clarify portal site record copy`
- `9d4c1852 Require account membership for portal access`

These commits are implementation evidence, not a promise that every old data
row has already been migrated or that `SiteUserGrant` has been removed from the
schema.

## Next-Stage Work

### P0: Audit and backfill legacy membership data

Before promoting the stricter membership rule to an environment containing old
Portal users:

1. find active principals with active site grants but no active membership for
   the site's account;
2. backfill one active membership when the target account is unambiguous;
3. report conflicting, missing-account, or multi-account rows for operator
   review;
4. add a repeatable integrity check so this drift cannot return;
5. verify that disabled principals and revoked memberships are not reactivated
   by the migration.

This is a data migration and integrity task. The account-membership code change
itself did not require a schema migration.

### P1: Make account membership the single Portal authorization truth

If product requirements remain account-scoped:

1. change Portal site list/detail/actions to authorize from active account
   membership;
2. stop creating new `SiteUserGrant` rows in Portal registration and site
   connection flows;
3. update Admin disable/audit output so it no longer presents grants as an
   independent authority;
4. add behavior tests for "account member can access every account site" and
   "non-member cannot access any account site";
5. only then remove obsolete repository methods, model references, and the
   `site_user_grants` table through Alembic.

If independent per-site ACLs become a real requirement, keep them explicitly as
an account-subordinate ACL and document how they interact with membership. Do
not restore them as a login fallback.

### P1: Complete addon-binding browser coverage

Add an end-to-end matrix covering:

- already-authenticated addon binding;
- login followed by return to the complete addon query;
- registration followed by direct binding completion;
- `localhost` versus `127.0.0.1` detection or canonical-host enforcement;
- reconnecting inactive/archived sites;
- duplicate state parameters and invalid/expired state handling;
- successful return to the WordPress `admin-post.php` callback.

### P2: Operate the support system as a measurable service

The support feature is functionally present. The next value comes from bounded
operations rather than more customer UI:

- response-time and unresolved-age summaries;
- attachment retention and size policy review;
- rating aggregation without exposing private messages;
- clear reopen policy for resolved versus closed requests;
- notification delivery diagnostics for customer/operator replies.

These should remain service evidence and operator detail, not grow into a full
CRM platform.

## Verification Expectations

Future work in this area should use the narrowest relevant checks plus the
default fast gate. At minimum:

- targeted Portal API tests in `tests/api/test_portal_routes.py`;
- Portal unit contracts for navigation, professional-information removal,
  package, usage, and support;
- frontend type-check and lint;
- browser coverage for login/session/addon return flows;
- `pnpm run check:fast` before closeout.

For authorization cleanup, tests must verify both positive access and
fail-closed behavior. For data migration, verification must include idempotency,
revoked-user preservation, and a zero-drift report after migration.

## Final Guardrail

The stable product rule from this history is:

```text
Portal is an account-scoped Cloud service center.
Sites are explicit connection records, not a global workspace switch.
WordPress remains the local control plane.
```
