# Cloud Hosted Runtime Profiles v1

Status: active.

Date: 2026-07-17.

## Purpose

Define the bounded Cloud operator contract for selecting the hosted runtime
candidate chain used by the current WordPress connector. This is a Cloud
runtime configuration surface, not an ability, workflow, prompt, preset,
approval, or CMS routing control plane.

## Current Scope

WordPress is the only implementation priority in this phase. The contract is
platform-tagged so a later Typecho, Z-BlogPHP, Ghost, or other CMS connector can
be added without pretending to be WordPress or creating a second Cloud runtime.

The current contract identity is:

- `platform_kind`: `wordpress`
- `connector_id`: `wordpress_ai_connector`
- `operation_contract_version`: `wordpress_operation.v1`
- `contract_version`: `cloud-hosted-runtime-profiles.v1`

This platform tag is an explicit seam, not a universal CMS registry.
`connector_id` names the WordPress hosted-profile family; it is not the
deployed connector implementation identifier carried by the public runtime
envelope. The public execution envelope remains the single
`cloud_connector_runtime.v1` contract and is not selectable from this Admin
resource. Profiles are selected from the validated platform-specific operation,
so this resource binds the WordPress operation contract explicitly.

## Ownership

Cloud owns:

- the hosted candidate instance chain for each supported runtime profile;
- runtime timeout, fallback, and bounded retry settings;
- provider/model availability and health evidence;
- the configuration revision and service-plane audit receipt.

The WordPress/plugin side owns:

- ability and workflow identity, schema, and enablement;
- task-to-profile adoption and the local router truth;
- prompts, presets, permissions, review, approval, and preflight;
- final WordPress writes and final local audit truth.

Cloud configuration can change how an already adopted hosted profile executes.
It cannot enable a plugin feature, adopt a profile for a site, or authorize a
WordPress write.

## Admin Contract

The only browser page is:

```text
/admin/runtime-profiles
```

The only internal service endpoints are:

```text
GET /internal/service/admin/runtime-profiles
PUT /internal/service/admin/runtime-profiles
```

The browser proxy exposes the exact matching `GET` and `PUT` methods at
`/api/admin/runtime-profiles` after platform-admin and catalog-management
authorization. Unknown methods and the retired `ability-models` paths fail
closed.

The read projection contains:

- explicit platform and connector identity;
- available runtime instances grouped by execution kind;
- supported hosted profiles and their ordered candidate instance IDs;
- the Cloud/local ownership boundary.

The write request must repeat `contract_version`, `platform_kind`,
`connector_id`, `operation_contract_version`, and the complete profile set.
Candidate instances, when present, must be available, enabled by the provider
model allowlist, compatible with the profile execution kind, and limited to a
primary plus one fallback. An empty candidate chain is an explicit fail-closed `needs_candidates` state, so a
missing media provider does not block unrelated profile configuration. Writes
require an idempotency key and return an auditable operator receipt. Existing
Cloud operator notes must round-trip unchanged when the page does not edit
them.

## Direct Cutover

The project has no production users and no compatibility requirement. The
following surfaces are deleted rather than aliased:

- `/admin/ability-models`;
- `GET /internal/service/admin/ability-models/runtime-projection`;
- `GET|POST /internal/service/admin/ability-models/plugin-routing`;
- `POST /internal/service/admin/ability-models/runtime-binding`.

The read-only Cloud dependency projection is removed from this workspace.
Site Knowledge embedding remains exclusively under `/admin/vector-settings`.
The constant-conflict runtime binding stub is removed. Audio generation remains
a supported runtime execution kind, but audio preview is removed from the
profile configuration page; provider/runtime diagnostics may gain a separate
bounded test surface only after a new contract review.

The browser proxy no longer exposes audio-job creation or polling. The internal
audio runtime API remains available to non-browser runtime consumers and is not
silently repurposed as an Admin diagnostic surface.

The superseded combined WordPress connector contract and its former identity
field are removed atomically from active code, persisted hosted-profile
policies, frontend consumers, and tests. There is no alias, dual read, or
fallback value.

## UI Contract

The page is a configuration workspace:

1. compact readiness and boundary summary;
2. hosted profile directory;
3. selected profile inspector;
4. candidate selection only inside the edit dialog;
5. one save action with an auditable receipt.

It must use the shared strict `ApiClient`. It must not fetch Site Knowledge
embedding state, create audio jobs, expose generated media bytes, or imply
ownership of WordPress abilities or writes.

## Verification

Use the focused backend, proxy, static frontend, and Playwright contracts for
the surface, then run:

```bash
pnpm run check:fast
pnpm run check:seam
pnpm run check:perimeter
pnpm run check:anti-drift
pnpm run lint
```
