# ADR-018: Contract Admin Around Hosted Runtime Profiles

## Status

Accepted.

## Date

2026-07-17.

## Context

The existing `/admin/ability-models` workspace combined four different jobs:

- WordPress connector hosted routing-profile configuration;
- a read-only projection of other Cloud runtime dependencies;
- Site Knowledge embedding configuration through an endpoint that always
  returned HTTP 409;
- an audio-generation preview experiment.

The name and composition suggested that Cloud owned ability-to-model truth even
though WordPress remains the ability, workflow, prompt, adoption, approval, and
write control plane. It also duplicated Vector Settings and mixed diagnostics
with configuration. The project has no production users, so preserving these
routes would add compatibility cost without customer value.

The current product priority remains WordPress. Future CMS support needs an
explicit platform seam, but not a universal CMS registry or parallel Cloud
runtime.

## Decision

Replace the mixed workspace with one platform-tagged hosted runtime profile
configuration surface:

- page: `/admin/runtime-profiles`;
- read: `GET /internal/service/admin/runtime-profiles`;
- write: `PUT /internal/service/admin/runtime-profiles`;
- platform: `wordpress`;
- connector: `wordpress_ai_connector`.

Cloud owns the ordered hosted candidate chain and bounded runtime policy. The
WordPress/plugin side keeps ability/workflow definitions, task adoption, local
router truth, prompts, approval, preflight, final writes, and final audit.

Delete the old page and all three `ability-models` endpoint families without
aliases. Remove the constant-409 binding stub, the duplicate Cloud dependency
projection, and the page-level audio preview. Keep Site Knowledge embedding in
Vector Settings and keep audio runtime execution independent of this admin UI.

Use a strict resource contract: `GET` reads the configuration and `PUT`
replaces the complete supported profile set. The write repeats both Cloud and
WordPress operation contract identities, permits an explicit empty fail-closed
candidate chain, limits the chain to a primary plus one fallback, and preserves
existing operator notes. Every write requires an idempotency key and returns an
audit receipt. The browser proxy allowlists only the exact new method/path
pairs.

The Admin resource uses `operation_contract_version=wordpress_operation.v1`.
It does not repeat the platform-neutral `cloud_connector_runtime.v1` envelope
as a selectable profile dimension. Its `connector_id=wordpress_ai_connector`
is the hosted-profile namespace and is intentionally distinct from the
deployed connector implementation identity carried by a runtime request.

## Alternatives Considered

### Keep `/admin/ability-models` and change only the label

Rejected because the duplicate projection, constant-conflict action, audio
experiment, raw request paths, and ownership ambiguity would remain.

### Keep compatibility aliases and redirects

Rejected because there are no production users. A dual route would create
tests and future removal work without protecting a real consumer.

### Build a universal multi-CMS profile registry now

Rejected because WordPress is the current delivery priority and there is no
second connector implementation to validate a universal abstraction. Explicit
platform and connector fields provide the necessary seam with less complexity.

### Move Site Knowledge embedding and audio diagnostics into the new page

Rejected because embedding already has a dedicated configuration owner and an
audio preview is a runtime/provider diagnostic, not profile truth.

## Consequences

- The Admin route and API contract change in one release with no compatibility
  path.
- The page loads one primary projection and uses the shared API transport.
- Operator language describes hosted execution configuration instead of Cloud
  ability ownership.
- WordPress-first profile IDs remain usable while their host platform and
  operation contract are explicit.
- The superseded combined connector identity is migrated out of current
  routing-profile policy JSON without changing candidate chains, notes, or
  revisions; no runtime compatibility branch remains.
- Future CMS work can add another platform-tagged connector implementation
  without copying the Cloud runtime or mixing host platforms with access
  channels.
- Audio preview may return only through a separately reviewed diagnostic
  surface; it is not silently relocated in this batch.

## Rollback

Application and policy data must roll back as one versioned unit. Stop the API
and workers, downgrade migration `20260717_0068` (or restore the verified
pre-migration backup), and only then start the previous application revision.
For promotion, stop the old API and workers, capture the required inventory and
backup evidence, apply `20260717_0068`, and then start the new revision. Do not
run old application code against upgraded policy JSON or new application code
against legacy policy JSON. No dual-read or dual-write compatibility state is
introduced; candidate chains, operator notes, revisions, and historical
run/audit evidence remain intact.

## References

- [Cloud Hosted Runtime Profiles v1](../cloud-hosted-runtime-profiles-v1.md)
- [WordPress-first Cloud Runtime Refactor](004-wordpress-first-cloud-runtime-refactor.md)
- [Cloud Admin Information Architecture v2](../cloud-admin-information-architecture-v2.md)
- [P4 Portal/Admin Surface Inventory](../p4-portal-admin-surface-inventory-2026-07-16.md)
