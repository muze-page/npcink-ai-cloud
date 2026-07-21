# ADR-004: Refactor WordPress First With Minimal Future CMS Seams

## Status

Accepted.

Stable markers: `WORDPRESS_FIRST`, `PLATFORM_CHANNEL_ORTHOGONAL`,
`LOCAL_CONTROL_PLANE`, `NO_FULL_REWRITE`, `NO_COMPATIBILITY_LAYER`,
`ONE_ACTIVE_CONTRACT_VERSION`.

## Date

2026-07-14.

## Context

Npcink AI Cloud is still in development and has no external users. The current
system already contains valuable hosted-runtime foundations, but some contracts
and modules retain WordPress-specific naming, oversized responsibility spans,
and proof-of-concept media storage paths. Preserving those structures behind
compatibility layers would make every later change slower without protecting a
real user.

WordPress is the current product and the only platform that must work during
this refactor. Typecho, Z-BlogPHP, Ghost, and additional media types remain
credible future directions, so new seams should avoid unnecessary WordPress
coupling. They must not, however, expand the current delivery scope into a
multi-CMS platform project.

The existing Cloud foundation is also substantial: stable principals and
commercial dimensions, sites and HMAC credentials, durable run records,
providers and routing, usage and entitlement evidence, health and diagnostics,
PostgreSQL, Redis wake-up support, workers, migrations, and production release
discipline. Replacing all of it would discard working evidence and create a
larger validation problem than the current architectural debt.

The ownership boundary is fixed. Cloud is the runtime and service enhancement
layer. WordPress/Core remains the local control plane for abilities, workflows,
prompts, presets, permissions, channel exposure, review, approval, preflight,
audit, and final WordPress writes.

## Decision

1. Follow a **`WORDPRESS_FIRST`** P0-P5 refactor. WordPress is the only accepted
   CMS platform during these phases. A Typecho proof of concept is a post-P5
   validation, not a P0-P5 deliverable.
2. Target one Cloud runtime with CMS-local adapters. Add only minimal future
   seams: `site_url`, `platform_kind`, `connector_id`, `connector_version`, and
   `object_type/object_id/object_revision`. This ADR does not claim those fields
   are implemented.
3. Enforce **`PLATFORM_CHANNEL_ORTHOGONAL`**. WordPress, Typecho, Z-BlogPHP, and
   Ghost are host platforms; editor, API, MCP, and OpenClaw are access channels.
   Implementations must not create platform-by-channel adapters or channel-local
   ability/workflow truth.
4. Keep `principals.principal_id` as the stable Cloud user identity. Keep
   account, membership, site, and local WordPress user references as separate
   dimensions.
5. Enforce **`LOCAL_CONTROL_PLANE`**. Keep Cloud limited to hosted execution,
   provider routing, usage and entitlement evidence, health and diagnostics,
   temporary artifacts, and bounded read-only runtime evidence. All local
   governance and final writes remain in WordPress/Core.
6. Hosted-first is not cloud-only. Preserve explicit local, offline, and
   privacy-sensitive execution seams. `run_records` is Cloud hosted durable run
   truth only and does not replace WordPress/Core local canonical run, proposal,
   or approval truth. During Cloud outage, the local contract decides whether
   to fail closed or use a governed fallback; Cloud does not own fallback truth.
7. Use **`NO_FULL_REWRITE`**. Retain FastAPI, PostgreSQL, Redis, workers,
   SQLAlchemy/Alembic, Docker Compose, `run_records`, provider/routing support,
   HMAC/nonce/idempotency, commercial evidence, diagnostics, and release
   discipline. Refactor responsibility boundaries incrementally in scoped
   batches.
8. Use **`NO_COMPATIBILITY_LAYER`**. When replacing `wordpress_url` with
   `site_url`, or replacing any route, model, or media path, delete its alias,
   fallback, dual read/write, deprecated route, fixture, and old test in the
   same integration milestone.
9. Enforce **`ONE_ACTIVE_CONTRACT_VERSION`**. A breaking change may use a new
   version during an atomic migration, but the replaced public version must be
   deleted before the milestone closes. The repository does not maintain
   long-lived v1/v2 implementations.
10. Refactor Media Runtime around streamed I/O, unified artifact metadata,
   short-lived site-scoped artifacts, signed pull, local verification, and
   local governed write. Media bytes must leave PostgreSQL blob columns and
   Base64 run payloads. A local-volume ArtifactStore is the first backend;
   object storage is implemented only when horizontal scaling evidence requires
   it.
11. Do not introduce a Cloud ability/capability registry, permanent media
    library, arbitrary processing DAG, direct WordPress write path, or new
    Kafka/Celery/Temporal/RabbitMQ/MinIO infrastructure during this refactor.

## Alternatives Considered

### Implement Multiple CMS Platforms Now

Rejected. It would split effort before the WordPress product loop is proven and
would encourage abstracting imagined differences. A later Typecho PoC provides
a stronger test: the Cloud main path must remain unchanged while a thin local
adapter supplies platform-specific permissions, context, review, and writes.

### Keep WordPress-specific Contracts Everywhere

Rejected. Names such as `wordpress_url` and WordPress-shaped object references
would force later adapters either to impersonate WordPress or to fork the Cloud
runtime. Minimal platform and object seams avoid that outcome without building
future adapters now.

### Rewrite Cloud From Zero

Rejected under `NO_FULL_REWRITE`. The current runtime, identity, auth,
commercial, provider, diagnostic, migration, deployment, and release
foundations are useful and boundary-aligned. A rewrite would increase scope,
erase proven behavior, and delay the real WordPress loop.

### Preserve Compatibility Until After The Refactor

Rejected under `NO_COMPATIBILITY_LAYER`. There are no external users to
protect, and temporary aliases, fallbacks, and dual writes tend to become
permanent ambiguity. Atomic producer/consumer/test/data changes are faster and
leave one observable behavior.

### Run Old And New API Versions In Parallel

Rejected under `ONE_ACTIVE_CONTRACT_VERSION`. Parallel public versions double
auth, validation, documentation, monitoring, and security surfaces. If a new
version is needed for a breaking transition, the old version is removed in the
same integration milestone.

### Introduce A General Orchestrator And Object Store Immediately

Rejected. The existing worker, Redis wake-up, PostgreSQL run truth, and a local
volume ArtifactStore cover the current requirement. Heavy infrastructure is
deferred until measured throughput, durability, or horizontal-scaling needs
prove it necessary.

## Consequences

Positive consequences:

- WordPress remains the single delivery focus, reducing time to a real product
  loop.
- Future CMS adapters receive clean platform and object seams without forcing
  the current project to implement them.
- Removing compatibility code reduces contract, test, security, and migration
  surface.
- Existing operational evidence and release discipline remain useful.
- Hosted availability does not erase local/offline/privacy-sensitive execution;
  local governance continues to own canonical runs, proposals, approvals, and
  fallback decisions.
- Media growth can reuse one transport and artifact lifecycle while keeping
  image generation, image transformation, and future processors type-specific.

Costs and risks:

- Breaking batches must update every producer, consumer, fixture, migration,
  test, and document together.
- Development databases may require resets; production-like configuration and
  service evidence still require inventory and backup before deletion.
- Smaller modules improve ownership only if cross-module contracts remain
  explicit; mechanical file splitting alone is insufficient.
- The future CMS seam remains a hypothesis until the Typecho PoC proves that no
  Cloud main-path rewrite is required.
- One active version demands disciplined milestone completion; incomplete
  transitions cannot be hidden behind a compatibility route.

## Implementation Sequence

1. **P0 — Contracts and baseline:** freeze target boundaries, deletion
   inventory, contract tests, and current performance/security evidence.
2. **P1 — Identity, site, and runtime foundation:** move to the single site and
   connector seam, modularize runtime responsibilities, and remove old names
   and paths.
3. **P2 — WordPress text loop:** prove title, summary, and selected-text rewrite
   through Cloud execution and local review/write governance.
4. **P3 — Media Runtime:** implement streaming, artifact storage and lifecycle,
   image processing/generation handoff, signed pull, local verification, and
   removal of database/Base64 media bytes.
5. **P4 — Portal/Admin contraction:** expose bounded Cloud detail without
   duplicating local control-plane truth.
6. **P5 — Hardening and release:** complete security/performance evidence,
   cross-repository matrices, deployment smoke, rollback checks, and the final
   completion audit.
7. **Post-P5:** validate the seam with a suggestion-only Typecho PoC before
   considering Z-BlogPHP or Ghost.

Each phase is delivered in single-module batches. The primary agent owns task
envelopes, boundary decisions, independent verification, milestone reports,
and Git. Multiple write-enabled subagents may run only across exclusive
repository/file allowlists; a shared file has one writer, and overlapping
batches run sequentially.

## Rollback

- Keep each batch independently reviewable and revert the entire batch rather
  than restoring an alias, fallback, dual write, or deprecated route.
- Before destructive schema work, record the current migration revision,
  affected data, production-like configuration and secret carry-forward plan,
  backup, and tested restore command.
- Developer data may be reset when the batch explicitly allows it; provider
  configuration, secrets, service audit evidence, and operational state must
  not be deleted merely because there are no external users.
- If focused gates, the cross-repository matrix, real WordPress behavior, or
  deployment smoke contradict the target contract, stop promotion and restore
  the last verified release.
- Replacing this decision requires a superseding ADR. It must preserve the
  Cloud-versus-local ownership boundary unless that boundary is separately and
  explicitly approved.
