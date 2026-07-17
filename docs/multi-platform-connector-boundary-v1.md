# Multi-platform Connector Boundary v1

## Status

Accepted target contract; not yet fully implemented.

This document defines the intended connector boundary for the WordPress-first
refactor. Current code and routes remain evidence of the starting point, not
proof that the target envelope or fields already exist.

## Purpose

Define one Cloud runtime seam that serves WordPress now and can later accept a
thin CMS-local adapter without cloning the runtime. Keep CMS host differences
local while preserving Cloud execution, trace, idempotency, storage, usage,
entitlement, health, and diagnostics behavior.

This contract does not expand P0-P5 into multi-CMS delivery. WordPress is the
only accepted platform until the refactor and its real product loops close.

## Stable Markers

- `WORDPRESS_ONLY_NOW`: P0-P5 implements and accepts WordPress only.
- `PLATFORM_CHANNEL_ORTHOGONAL`: host platform and access channel are separate.
- `LOCAL_CAPABILITY_TRUTH`: capability, permission, and governance truth stays local.
- `ONE_CLOUD_RUNTIME`: platforms reuse one hosted execution path.
- `SUGGESTION_ONLY`: Cloud returns suggestions or read-only artifacts by default.

## Current Evidence And Target State

Current evidence includes `wp_ai_connector_runtime.v1`, its WordPress task
allowlist, `suggestion_only` write posture, direct-write rejection, bounded
request validation, and structured `wp_ai_connector.*` errors. It proves that a
signed WordPress connector can use the hosted runtime safely.

The target is not fully implemented. The current contract still combines a
WordPress connector identity, task semantics, and runtime envelope. P1 must
separate a neutral envelope from the WordPress-specific operation contract,
not merely rename every WordPress concept and pretend the result is generic.

The transition has no compatibility requirement. When the target contract is
implemented, producers, consumers, tests, fixtures, and documentation change
atomically and the superseded public contract is removed.

## Two Orthogonal Axes

| Axis | Values and examples | Ownership rule |
| --- | --- | --- |
| Host platform | WordPress now; Typecho, Z-BlogPHP, and Ghost are future validation candidates | A CMS-local adapter owns host APIs, permissions, objects, review, and writes. |
| Access channel | editor, API, MCP, OpenClaw | Channels consume local capability projections; they are not CMS adapters or truth sources. |

`PLATFORM_CHANNEL_ORTHOGONAL` forbids WordPress-editor, WordPress-MCP,
Typecho-editor, and Typecho-MCP runtime adapter variants. A channel selects an
approved local capability; a host adapter supplies the platform integration.

P0-P5 accepts only `platform_kind=wordpress`. Typecho, Z-BlogPHP, and Ghost are
future candidates only, not current enum values or dormant Cloud branches.

“CMS-local adapter” is a logical host-platform role. WordPress Cloud Addon or
local integration code may carry it; `npcink-ai-client-adapter` is an
OpenClaw/MCP access-channel adapter, not a WordPress host adapter, and owns no
CMS permission, write, or capability truth.

## Ownership Matrix

| Layer | Owns | Must not own |
| --- | --- | --- |
| Cloud | hosted execution, provider routing, Cloud run evidence, usage and entitlement evidence, temporary artifacts, health, and diagnostics | CMS permissions, abilities, workflows, prompts, presets, review, approval, audit, or final CMS writes |
| Cross-platform runtime envelope | transport identity, connector/version facts, trace, idempotency, storage posture, object reference, and result posture | CMS object semantics, channel exposure truth, or a second capability model |
| CMS-local adapter | permission checks, context extraction, request signing, result review, local apply handoff, and local audit correlation | hosted provider execution, Cloud commercial truth, or durable Cloud run truth |
| CMS | content, users, roles, taxonomies, media, comments, local governance, and final write truth | Cloud provider routing, hosted usage, or Cloud runtime diagnostics |

Cloud remains runtime/detail only. The adapter remains thin transport and local
integration. Neither becomes a second control plane.

## Identity And Resource Dimensions

`principal_id` is the single stable Cloud user identity. It is server-owned and
must not be inferred from a CMS user, email, account, membership, or site.

| Dimension | Meaning |
| --- | --- |
| `principal_id` | stable Cloud user identity |
| `account_id` | commercial account or tenant |
| `membership_id` | relationship between a principal and an account |
| `site_id` | provisioned Cloud site resource and signing scope |
| `wp_user_id` | optional WordPress-local actor reference only |

An account, membership, site, or `wp_user_id` is not a user identity. A local
actor reference never grants Cloud permission and never replaces the local
permission check.

## Target Runtime Envelope

The target logical envelope carries the following fields. This table describes
the accepted target, not current implementation evidence.

| Field | Required semantics |
| --- | --- |
| `site_id` | provisioned, active, authenticated site scope |
| `site_url` | canonical CMS site URL |
| `platform_kind` | `wordpress` only during P0-P5 |
| `connector_id` | stable connector implementation identity |
| `connector_version` | deployed connector implementation version |
| `contract_version` | one active platform-neutral envelope version |
| `trace_id` | end-to-end correlation identifier |
| `idempotency_key` | site-scoped write-request replay identity |
| `storage_mode` | `no_store`, `result_only`, or `full_store_with_ttl` |
| `suggestion_only` | must be `true` for the WordPress P0-P5 connector path |
| `object_ref` | optional platform-neutral resource reference |
| `operation_contract` | locally owned, approved, platform-specific operation contract |

Existing runtime facts such as ability name, family, channel, profile,
execution kind, data classification, timeout, retry, and retention may remain
bounded runtime fields. Their presence does not create a Cloud ability model.

`operation_contract` is validated input to an approved runtime gate. Cloud does
not register, discover, edit, publish, or govern those contracts. WordPress
operation semantics remain explicitly WordPress-specific inside that contract.

`wordpress_url` is not part of the target. P1 must replace it with `site_url`
without an alias, fallback, compatibility shim, dual read, or dual write.

## Platform-neutral Object Reference

When a request concerns a CMS object, `object_ref` has exactly these identity
fields:

```json
{
  "object_type": "post",
  "object_id": "123",
  "object_revision": "456"
}
```

- `object_type` identifies the local object category without defining a
  universal CMS content model.
- `object_id` is an opaque identifier within the authenticated site.
- `object_revision` is the local version used for stale-result detection.

Cloud may correlate and return this reference. It must not infer CMS
permissions, resolve local ownership, or treat the reference as write authority.

## Capability And Permission Projection

`LOCAL_CAPABILITY_TRUTH` requires the CMS-local stack to own abilities,
workflows, prompts, presets, schemas, channel admission, risk, confirmation,
permissions, and apply rules.

The adapter may project only the bounded runtime facts required by an approved
contract. Cloud may validate and execute that projection, meter it, and return
evidence. Cloud must not maintain a capability list, CMS ability registry,
workflow registry, prompt library, preset registry, MCP registry, or OpenClaw
registry.

Permission evaluation happens locally before signing. The local adapter must
also recheck any permission, revision, approval, and preflight requirements
before applying a returned result. A successful Cloud run grants no CMS write
permission.

Channel exposure is projected from local truth. An editor, API, MCP, or
OpenClaw consumer may present the same capability differently but must not
invent a separate schema, permission rule, or write posture.

## Version, Idempotency, And Error Semantics

Only one public connector envelope version may be active in an integration
milestone. A breaking upgrade may cut to a new version, but the old route,
validator, producer, consumer, fixtures, and tests are deleted before the
milestone closes.

There is no long-lived v1/v2 coexistence, version negotiation, compatibility
alias, or fallback parsing. `connector_version` reports implementation facts;
it does not select a second public contract.

`idempotency_key` is scoped by authenticated `site_id`. Repeating the same key
and semantic request returns the same Cloud run evidence. Reusing the key with
a different semantic request fails closed with an idempotency conflict.

Errors use stable machine-readable codes with a bounded namespace and include
the relevant `trace_id`. Validation, authentication, authorization,
idempotency, entitlement, runtime, provider, and result-expiry failures remain
distinguishable. Error messages must not expose secrets or provider internals.

## Security And Write Boundary

The CMS-local adapter handles local authentication, permissions, bounded
context, signing, nonce/timestamp, result review, apply, and audit correlation.

Cloud authenticates the provisioned site, verifies HMAC/body digest, required
scope, timestamp, nonce, request size, contract, and idempotency before
execution. A site can access only its own runs and artifacts.

Cloud results default to `SUGGESTION_ONLY`: reviewable suggestions, temporary
artifacts, or read-only runtime evidence. Cloud never saves a post, publishes
content, changes taxonomy, imports media, replaces an attachment, or assigns a
featured image.

Final review, approval, preflight, audit, stale-revision checking, and CMS write
occur locally. Callback delivery is a notification; signed pull remains the
result path and neither callback nor delivery acknowledgment means “applied.”

## Keep / Change / Delete / Defer

| Action | Scope |
| --- | --- |
| Keep | existing hosted runtime, HMAC, idempotency, run evidence, provider routing, usage, entitlement, worker, health, diagnostics, and local governance ownership |
| Change | split the neutral envelope from WordPress-specific operation semantics; add target site, platform, connector, object, and result-posture fields |
| Delete | `wordpress_url`, obsolete connector envelope, aliases, fallback parsing, dual reads/writes, superseded fixtures, and duplicate version tests when P1 lands |
| Defer | Typecho, Z-BlogPHP, Ghost adapters, shared SDK extraction, new channel products, and universal CMS content modeling |

## WordPress Acceptance For P0-P5

- `platform_kind` accepts only `wordpress`.
- One WordPress adapter calls the existing Cloud main execution path.
- The adapter owns local permission, context, signing, review, apply, and audit; title, summary, and rewrite results remain suggestions.
- `site_url`, connector identity/version, trace, idempotency, storage, and object references are preserved end to end.
- Retries do not duplicate Cloud execution or local writes.
- Cloud outage fails closed or uses a locally governed fallback; no Cloud registry, workflow/approval truth, or WordPress write path appears.
- The old public connector contract and `wordpress_url` compatibility paths are absent after P1 closes.

## Post-P5 Typecho PoC Acceptance

After P5, a thin Typecho adapter may validate exactly three suggestion-only
tasks: title suggestion, content summary, and selected-text rewrite.

The PoC must reuse the same Cloud main execution path, runtime envelope,
idempotency, error semantics, result posture, and diagnostics. Typecho supplies
its own local hooks, permission checks, context extraction, review, apply, and
audit behavior. It must not identify itself as WordPress.

If the PoC requires a Typecho-specific Cloud runtime, new Cloud capability
registry, duplicated queue, or rewrite of the Cloud main path, this contract
has failed and must be corrected before considering Z-BlogPHP or Ghost.

## Non-goals

- Implementing Typecho, Z-BlogPHP, or Ghost during P0-P5, or creating a universal CMS model.
- Creating platform-by-channel adapters or moving local capability/channel truth into Cloud.
- Moving review, approval, audit, fallback choice, or writes into Cloud.
- Keeping `wordpress_url`, dual contracts, aliases, multiple active versions, or a second runtime/control plane.
