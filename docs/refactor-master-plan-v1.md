# Npcink AI Cloud Refactor Master Plan v1

## Status

Accepted target contract. This document describes the intended end state and
delivery sequence; it does not claim that target fields, routes, storage, or
module splits are already implemented.

Stable markers: `WORDPRESS_FIRST`, `PLATFORM_CHANNEL_ORTHOGONAL`,
`LOCAL_CONTROL_PLANE`, `NO_COMPATIBILITY_LAYER`,
`ONE_ACTIVE_CONTRACT_VERSION`.

## Context

Npcink AI Cloud is under active development and has no external users. This is
the lowest-cost point to remove obsolete contracts and structural debt instead
of preserving them behind aliases, fallbacks, or parallel implementations.

The immediate product target is a production-quality WordPress hosted runtime
loop. Typecho, Z-BlogPHP, Ghost, additional access channels, and additional
media types are future validation targets, not current implementation scope.
The target shape is one Cloud runtime with CMS-local adapters. CMS host
platforms and access channels are orthogonal dimensions: a WordPress editor,
MCP, OpenClaw, and an API are not four CMS adapters.

## Current Evidence

- The repository README defines Cloud as the hosted runtime enhancement layer,
  not a second control plane or source of truth.
- The hosted runtime already has FastAPI, PostgreSQL, Redis wake-up support,
  workers, provider routing, usage and entitlement handling, diagnostics, HMAC
  request signing, nonce/idempotency guards, and durable `run_records` truth.
- `principals.principal_id` is already the stable Cloud user identity under
  ADR-003. Accounts, memberships, sites, and local WordPress users are separate
  resource dimensions.
- Existing boundary contracts keep ability, workflow, prompt, preset,
  permission, review, approval, preflight, audit, and final write truth local.
- Existing media work proves the product direction, while the target refactor
  still needs a unified artifact envelope, streaming I/O, and byte-storage
  separation from relational runtime truth.

## Goals

1. Deliver one reliable WordPress-to-Cloud text and media runtime path.
2. Preserve one stable identity hierarchy:
   `principal_id`, `account_id`, `membership_id`, and `site_id` keep distinct
   meanings; a local `wp_user_id` never becomes Cloud user identity.
3. Establish minimal future seams without implementing future CMS adapters:
   `site_url`, `platform_kind`, `connector_id`, `connector_version`, and a
   generic object reference.
4. Split oversized runtime modules by responsibility while retaining the
   existing runtime, provider, commercial, and operational foundations.
5. Make media transfer temporary, streamed, site-scoped, measurable, and safe.
6. Remove obsolete contracts immediately so only one active implementation and
   one active public contract version remain.
7. Prove completion with focused tests, boundary gates, cross-repository
   matrices, deployment smoke tests, and real WordPress end-to-end evidence.

## Non-goals

- Implementing Typecho, Z-BlogPHP, Ghost, audio, or video support now.
- Building a Cloud ability, capability, workflow, prompt, preset, MCP, or
  OpenClaw registry.
- Moving WordPress permissions, review, approval, preflight, audit, or final
  writes into Cloud.
- Rewriting the Cloud from zero or replacing the current approved stack.
- Building a permanent Cloud media library, arbitrary media DAG, or direct
  Cloud-to-WordPress write path.
- Introducing Kafka, Celery, Temporal, RabbitMQ, MinIO, or a second scheduler or
  workflow truth during this refactor.
- Maintaining deprecated routes, aliases, shims, dual reads, dual writes, or
  long-lived v1/v2 implementations.

## Boundary Invariants

1. **`LOCAL_CONTROL_PLANE`:** WordPress/Core owns ability, workflow, prompt,
   preset, channel exposure, permissions, review, approval, preflight, audit,
   and final write truth.
2. Cloud owns hosted execution, provider routing, usage and entitlement
   evidence, health and diagnostics, temporary artifacts, and bounded read-only
   runtime evidence.
3. `run_records` remains the Cloud hosted durable run truth only. It does not
   replace WordPress/Core local canonical run, proposal, or approval truth.
   Redis remains a wake-up, bounded queue-assist, replay, and pressure-support
   mechanism only.
4. `principals.principal_id` is the stable Cloud user identity. `account_id`,
   `membership_id`, `site_id`, and `wp_user_id` must not impersonate it.
5. **`PLATFORM_CHANNEL_ORTHOGONAL`:** CMS platform and access channel are
   separate axes. Cloud must not create platform-by-channel adapter variants.
6. This refactor remains **`WORDPRESS_FIRST`**. During P0-P5,
   `platform_kind` accepts WordPress only; future values require a validated
   adapter milestone.
7. There is no Cloud capability registry. Capability and channel projections
   are consumed runtime facts whose governing truth remains local.
8. All WordPress writes return through local governance. Cloud responses remain
   suggestions, temporary artifacts, or read-only evidence.
9. **`NO_COMPATIBILITY_LAYER`:** obsolete fields, routes, fallbacks, fixtures,
   and tests are removed with their replacements.
10. **`ONE_ACTIVE_CONTRACT_VERSION`:** a breaking version change may use a new
    route or contract version, but the replaced version is deleted in the same
    integration milestone. Long-term v1/v2 coexistence is forbidden.
11. Hosted-first is not cloud-only. Preserve an explicit
    local/offline/privacy-sensitive fallback seam. On Cloud outage, the local
    contract decides whether to fail closed or use a governed fallback; Cloud
    does not own fallback truth.

## Retain / Change / Delete / Defer Matrix

| Action | Scope | Required outcome |
| --- | --- | --- |
| Retain | Identity and tenancy | Keep `principal_id`, account, membership, and site as separate dimensions. |
| Retain | Runtime foundation | Keep FastAPI, PostgreSQL, Redis, workers, SQLAlchemy/Alembic, Docker Compose, providers, routing, HMAC/nonce/idempotency, usage, entitlement, diagnostics, and production release discipline. |
| Retain | Run truth | Keep `run_records` as Cloud hosted durable truth only; do not promote it, Redis, or callbacks over WordPress/Core local canonical run, proposal, and approval truth. |
| Retain | Local fallback seam | Keep explicit local, offline, and privacy-sensitive execution paths; the local contract owns fail-closed versus governed fallback behavior during Cloud outage. |
| Change | Site contract | Replace `wordpress_url` with `site_url`; add `platform_kind=wordpress`, `connector_id`, and `connector_version` without fallback or alias. |
| Change | Runtime modules | Modularize `runtime/service.py` and other oversized services by run lifecycle, execution, queue, artifact, usage, and delivery responsibilities without creating a second runtime. |
| Change | Object reference | Use `object_type`, `object_id`, and `object_revision` as the platform-neutral runtime reference; keep local object semantics and permissions local. |
| Change | Media transport | Move to streamed upload/download, unified `MediaArtifact` metadata, short TTL, signed pull, delivery acknowledgement, and an `ArtifactStore` abstraction. |
| Delete | Compatibility | Delete deprecated routes, old field aliases, scattered fallbacks, dual reads/writes, compatibility fixtures, and old tests when the replacement lands. |
| Delete | Media byte persistence | Remove media blobs from PostgreSQL and Base64 media payloads from `run_records`; relational tables retain metadata and evidence only. |
| Defer | CMS implementations | Defer Typecho, Z-BlogPHP, and Ghost adapters until P0-P5 is complete and WordPress evidence is stable. |
| Defer | More media processors | Defer audio/video processors, resumable uploads, permanent media storage, CDN/gallery features, arbitrary operation DAGs, and S3-compatible storage until measured need exists. |

## Phased Sequence

### P0 — Target Contracts And Baseline

Deliverables:

- this master plan and ADR-004;
- cross-platform connector and Media Runtime target contracts;
- machine-readable contract tests for stable hard rules;
- current API/schema/module deletion inventory;
- security and performance baselines for text and media paths.

Required gates:

- focused target-contract tests;
- documentation link and marker checks;
- `pnpm run check:fast` after the complete P0 contract set lands.

Exit criteria:

- every later batch has a frozen owner, non-goals, public contracts, expected
  files, required gates, and rollback path;
- target documents clearly distinguish current evidence from not-yet-implemented
  contracts;
- the deletion inventory has an owning phase for every item.

### P1 — Identity, Site, And Runtime Foundation

Deliverables:

- canonical site contract using only `site_url` and
  `platform_kind=wordpress`;
- connector metadata and generic object reference at the runtime seam;
- one identity/site/runtime request envelope using existing trace,
  idempotency, storage, and suggestion posture;
- runtime service modularization with unchanged durable run ownership;
- synchronized migrations, callers, fixtures, and documentation;
- deletion of `wordpress_url`, old fallbacks, and superseded tests.

Required gates:

- focused identity, site, auth, idempotency, runtime, migration, and API tests;
- `pnpm run check:fast`;
- `pnpm run check:seam` and `pnpm run check:perimeter`.

Exit criteria:

- repository searches and tests prove there is no active `wordpress_url`
  contract or compatibility path;
- repeated requests preserve idempotency and site isolation;
- module boundaries no longer require one oversized service to own unrelated
  commercial, artifact, and delivery behavior;
- no Cloud control-plane truth has been introduced.

### P2 — WordPress Text Runtime Loop

Deliverables:

- real WordPress paths for title suggestions, summaries, and selected-text
  rewrites through the hosted runtime;
- honest provider/model/runtime evidence and consistent error handling;
- local review, approval, audit, and final-write handoff;
- an explicit local/offline/privacy-sensitive fallback seam whose local
  contract decides fail-closed versus governed fallback during Cloud outage;
- fail-closed behavior for entitlement denial, invalid auth, and idempotency
  conflict.

Required gates:

- focused Cloud text-runtime and WordPress consumer contract tests;
- real local WordPress smoke for request, result, review, and local apply;
- `pnpm run check:fast`, `pnpm run check:seam`, and the relevant local plugin
  gates.

Exit criteria:

- the three target tasks complete through the normal WordPress product path;
- Cloud never applies or publishes content;
- retries do not duplicate execution or local writes;
- failure evidence identifies the actual stage and remains auditable.

### P3 — Media Runtime

Deliverables:

- unified `MediaArtifact` metadata and pluggable `ArtifactStore`;
- a local-volume ArtifactStore as the first backend;
- streamed ingest and download, typed image operation contracts, queue-backed
  processing, signed pull, delivery acknowledgement, TTL, and purge;
- MIME/file-header/decode validation, dimension and pixel limits, default
  EXIF/GPS removal, checksum verification, and site isolation;
- distinct image transform and image generation contracts returning one
  artifact envelope;
- WordPress preview, local verification, review, and governed media import;
- removal of PostgreSQL media blobs and Base64 media data in run records.

Required gates:

- focused upload, worker, artifact, security, expiry, cleanup, retry, and site
  isolation tests;
- bounded-memory streaming verification;
- real WordPress upload-to-local-import smoke;
- `pnpm run check:fast`, `pnpm run check:seam`,
  `pnpm run check:perimeter`, and `pnpm run check:anti-drift`.

Exit criteria:

- media bytes do not enter PostgreSQL blobs, run-record Base64, logs, or audit
  payloads;
- source and result artifacts expire and purge as contracted;
- WordPress verifies the downloaded result before local review and write;
- Cloud does not push files to arbitrary site URLs or mutate WordPress media.

### P4 — Portal And Admin Contraction

Deliverables:

- one consistent API client, error model, and identity/account/site projection;
- bounded Portal views for connection, usage, entitlement, billing, health,
  run evidence, and diagnostics;
- bounded Admin views for service operations and diagnosis;
- removal of duplicate truth, historical debug pages, and obsolete copy.

Required gates:

- focused API authorization and frontend contract tests;
- frontend type-check and lint;
- `pnpm run check:fast`, `pnpm run check:seam`,
  `pnpm run check:perimeter`, and `pnpm run check:anti-drift`.

Exit criteria:

- Portal/Admin explain Cloud state without exposing secrets or duplicating
  WordPress abilities, workflows, prompts, approvals, or write controls;
- cross-account and cross-site authorization tests fail closed;
- every displayed value has one named authoritative owner.

### P5 — Hardening, Matrix, And Release Closure

Current status (2026-07-19):

- P5-B4 has passed bounded engineering acceptance at revision `dff31baf`;
  evidence: [P5-B4 runtime load/soak closeout](p5-b4-runtime-load-soak-closeout-2026-07-19.md).
- The formal dual-worker proof completed three independent baselines with all
  29 checks passing in each baseline. Queue p95 was `4.6318s`, `5.0296s`, and
  `4.7298s`; transport errors and HTTP 5xx responses remained zero. The formal
  hot-query proof and current-revision media replay also passed.
- This is engineering evidence for the proof topology, not a production SLO or
  production-release authorization. The proof-only dual-worker topology does
  not change the production single-worker default.
- P5-B6 production-topology contraction has passed engineering acceptance at
  revision `fb58e354`; evidence:
  [P5-B6 production topology contraction closeout](p5-b6-production-topology-contraction-closeout-2026-07-19.md).
- P5-B6 removes bundled Caddy, Jaeger, and the OTel Collector, pins the
  external-Edge/NGINX/Gunicorn trust chain, and closes the two independent P1
  migration findings. It does not supply the clean-tree image scan/bundle or
  production Edge evidence.
- P5-B7 exact-image and bundle engineering acceptance passed at revision
  `0663d95f`; evidence:
  [P5-B7 exact release bundle closeout](p5-b7-exact-release-bundle-closeout-2026-07-19.md).
  The clean `linux/arm64` bundle passed five-image scanning, archive and
  post-load identity checks, same-bundle double replay, migration, seed,
  health, and cleanup. Its three exact Python findings are covered only by the
  named temporary engineering exception through `2026-08-05`.
- P5-B8 and global P5 remain incomplete. No production promotion or deployment
  is authorized by the P5-B4, P5-B6, or P5-B7 result.

Deliverables:

- remaining obsolete-code deletion and dependency/security review;
- before/after API latency, query, queue, worker-memory, and streaming-memory
  evidence;
- completed failure recovery, cleanup, deployment, and rollback runbooks;
- exact deploy-bundle replay and real WordPress end-to-end acceptance record;
- final requirement-by-requirement completion audit.

Required gates:

- `pnpm run check:fast`;
- `pnpm run check:seam`;
- `pnpm run check:perimeter`;
- `pnpm run check:anti-drift`;
- `pnpm run lint`;
- all focused Cloud and WordPress suites named by P1-P4;
- `composer quality:matrix:run` from
  `/Users/muze/gitee/npcink-workflow-toolbox`;
- exact deploy-bundle smoke and production release-policy check.

Exit criteria:

- all P0-P5 deliverables are present and every explicit gate passes, or an
  exact accepted exception names its owner and evidence;
- real WordPress text and media loops pass through local governance;
- performance and memory claims are supported by before/after measurements;
- production scope, rollback, secrets/config carry-forward, and release policy
  are verified.

## Post-P5 Validation — Typecho PoC

Only after P5, validate the cross-platform seam with a thin Typecho adapter for
title suggestion, summary, and selected-text rewrite. It must reuse the Cloud
main path without a Typecho runtime, Typecho ability registry, or new workflow
truth. If the PoC requires a main-path rewrite, return to the target contract
and correct the seam before adding Z-BlogPHP or Ghost.

## Cross-repository Milestone Rule

Repository-local gates are necessary but do not close a milestone that changes
Cloud/WordPress contracts. For P2, P3, and P5 closeout, run the central matrix
from `/Users/muze/gitee/npcink-workflow-toolbox`:

```bash
composer quality:matrix:run
```

Do not copy the matrix into Cloud. Record the exact command, repositories and
revisions tested, failures, skips, and real WordPress evidence in the milestone
report.

## Breaking And Data Policy

- The project has no external users, so the default policy is direct
  replacement, not compatibility preservation.
- Removing or renaming a contract updates its producers, consumers, fixtures,
  tests, migrations, and documentation in one integration milestone.
- No alias, deprecated route, shim, fallback, dual read, dual write, or legacy
  fixture survives the milestone.
- Developer databases may be reset when that is faster and the batch contract
  explicitly permits it.
- No-user status does not authorize blind deletion of production provider
  configuration, secrets, service audit evidence, or operational state. Back up
  and inventory these before a destructive migration.
- A breaking API may introduce a new version only for the atomic transition;
  the replaced version is removed before milestone exit, preserving
  `ONE_ACTIVE_CONTRACT_VERSION`.

## Rollback

- Each batch produces one scoped, independently reviewable commit after its
  focused gates pass.
- Before a destructive schema batch, capture the current migration revision,
  data inventory, configuration/secret carry-forward plan, and a tested restore
  path.
- Roll back the whole batch—code, schema, consumers, fixtures, tests, and
  documentation—rather than restoring a compatibility shim.
- If production evidence contradicts a target contract, stop promotion, restore
  the last verified release, record the exact failure, and revise the contract
  in a new reviewed batch.
- Production changes continue to follow
  `docs/cloud-production-release-policy-v1.md`; no direct production source edit
  becomes canonical.

## Subagent Batch Discipline

- The primary agent owns architecture, task envelopes, boundary decisions,
  independent acceptance, milestone reporting, and all Git operations.
- Multiple write-enabled implementation subagents may run concurrently only
  when each receives an exclusive repository/file allowlist. A shared file has
  one writer, and batches that need the same file run sequentially.
- A subagent receives exactly one module, explicit allowed and forbidden files,
  non-goals, public-contract impact, gates, and rollback path.
- Subagents do not stage, commit, push, branch, rebase, reset, clean, or spawn
  additional agents.
- Read-only research or review may run separately only against a stable scope;
  its report never substitutes for primary-agent verification.
- The primary agent reviews the real diff and independently reruns the narrowest
  decisive tests before staging explicit files.
- The primary agent stops concurrent work if an ownership overlap appears;
  disjoint paths improve throughput but never weaken review or gate ownership.
- A failed review returns to the same batch for bounded rework. A boundary error
  terminates and re-plans the batch instead of expanding it silently.

## Final Completion Audit

The refactor is complete only when the primary agent builds a requirement-to-
evidence table covering every P0-P5 deliverable, hard invariant, named gate,
data policy, WordPress text/media flow, performance claim, deployment check,
and rollback requirement.

For every row, the audit must cite current authoritative evidence: file or
migration, focused test output, repository search, cross-repository matrix,
runtime result, real WordPress behavior, deployment smoke, or release record.
Missing, indirect, stale, skipped, or merely plausible evidence means the item
is incomplete. Completion cannot be inferred from a green narrow test, a
subagent report, or absence of obvious failures.

## Current Engineering Resolution — 2026-07-19

This is an append-only current-status resolution. It does not rewrite the
target contract or historical phase evidence.

The P5-B8 code-owned/local engineering gate set is `passed` at Cloud
implementation HEAD `054ae3d81e7beb43523c12581f8764e80080855b`, and the
P0-P5 architecture is frozen. Global P5 and the overall refactor phase-exit
remain incomplete until the operator-only P1-E05/P1-E06 evidence exists. The
complete requirement-to-evidence audit is
[P5-B8 Final Engineering Closeout](p5-b8-final-engineering-closeout-2026-07-19.md).
It records the exact WordPress package set, local text and media behavior,
performance, the last exact release payload, synthetic restore drill,
dependency policy, final Cloud/plugin gates, strict matrix, rollback, and
material failed-first-path caveats.

The exact bundle remains bound to the last release-payload revision
`0663d95f765a8c49154aac0536e26cbb51029094`, SHA-256
`592d1ce23334cddf4a09db0f147d6db48aa1c696980adc24630ed333660baa17`.
Changes through `054ae3d8` are documentation and Dependabot/release-policy
checker contract changes only; they do not change `app/**`, `frontend/**`,
Compose, deploy payload, or the image lock.

This does not unconditionally complete the refactor's production phase-exit
requirements. P1-E05 production title execution and P1-E06 production-like
inventory/carry-forward/restore remain operator-only and are
`production-only not claimed`; both block production promotion and GA. The
three named Python 3.14.6 CVE exceptions remain engineering-only through
`2026-08-05`. `linux/amd64`, production Edge/DNS/WAF/TLS/OTLP/secrets,
production backup/RPO/RTO, penetration testing, live provider quality, and
real-user value are also `production-only not claimed`. External object storage
remains a deferred non-goal rather than a production prerequisite.

The next stage is production/operator readiness plus a bounded real-provider
WordPress editorial/media trial. Typecho suggestion-only validation may be
considered after that evidence; Typecho, Z-BlogPHP, Ghost, and additional media
types remain post-P5 rather than current implementation scope.

## Integration Correction — 2026-07-20

This append-only correction records integration work after the 2026-07-19
resolution; it does not rewrite or upgrade the historical P5-B7/P5-B8 evidence.

- The production deploy contract now uses one serialized atomic cutover:
  prepare exact images, stop old public/write services, retain/start data
  services, migrate and refresh through staged one-off API containers, move the
  release pointer, start API, start and prove the new worker generation, pass
  generic operational readiness, and only then restore traffic.
- `.env.deploy` is never part of a release payload. Each managed release owns
  external state at `${REMOTE_DIR}/.release-state/<release-name>/env.deploy`
  under `0700/0600` permissions. Old and new Compose project names must match
  before mutation.
- Migration-started failures are fail-closed and do not automatically start the
  old application. Incomplete recovery evidence retains the deployment lock;
  successful cutover retains the per-release env state and removes only the
  temporary rollback-image map/tags.
- The historical `0663d95f` bundle remains exact `linux/arm64` evidence for that
  revision only. It is not current branch, `linux/amd64`, merged `master`, or
  production artifact evidence.
- After the integration branch is merged into `master`, the exact production
  image set must be rebuilt for `linux/amd64`, scanned, manifested, and replayed
  twice from that merged revision before P1-E05/P1-E06 or production promotion
  can use it.
