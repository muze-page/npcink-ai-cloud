# P5 Hardening And Release Audit — 2026-07-17

## Status

P5-A audit complete; global P5 release closure incomplete.

This is a requirement-to-evidence and gap record. It is not production
approval, a deployment record, a penetration test, a production SLO, or proof
that P1, P2, or P5 exited.

Audit input revision: `22eff1e0f455` on
`codex/p4-portal-context-contraction`. The P4 input revision was pushed to
GitHub before this audit. The P5-A documentation and contract changes belong to
the commit containing this record.

## Boundary And Non-goals

- Cloud remains hosted runtime, provider/runtime configuration, usage,
  entitlement, temporary-artifact, health, and diagnostic truth only.
- WordPress/Core remains the permission, ability, workflow, prompt, review,
  approval, apply, final-audit, and CMS-write owner.
- Media delivery acknowledgement remains transfer evidence only.
- Redis, queues, callbacks, buffers, and projections remain non-canonical.
- This audit does not add Typecho, Z-BlogPHP, Ghost, audio/video/document
  processors, a new queue, scheduler, workflow engine, registry, or control
  plane.
- No production deploy, paid-provider execution, credential rotation, or
  production cleanup enablement occurred.

## Phase Status

| Phase | Status | Current authoritative conclusion |
| --- | --- | --- |
| P0 | substantially complete | Target contracts, ADR-004, deletion inventory, baseline, and executable target-contract checks exist. Phase-level plans do not substitute for later exit evidence. |
| P1 | incomplete | `site_url`, `platform_kind=wordpress`, and runtime responsibility extraction are implemented. The superseded connector marker and operator-only `P1-E05`/`P1-E06` evidence remain open. |
| P2 | incomplete | The current Cloud/Add-on contracts support title, summary, and selected-text rewrite, but no current exact-package WordPress request/review/apply record covers all three tasks and their failure/idempotency posture. |
| P3 | complete for the bounded media milestone | P3-B5 records exact packages, fresh WordPress E2E, bounded memory, security, recovery, old-alias deletion, a six-repository matrix, and independent review. Current P5 still needs a replay against current revisions. |
| P4 | complete | The Portal/Admin inventory, destructive contraction, strict clients, fail-closed authorization, hot-path cleanup, focused gates, and screenshot-backed browser evidence are recorded. |
| P5 | incomplete | Dependency/security blockers, load/soak evidence, current exact bundle, current text/media WordPress acceptance, current matrix, restore rehearsal, release-policy proof, and the final audit remain open. |

## Structural Remeasurement

Commands were rerun against `app` and `tests` at the audit input revision. Raw
matching-line counts are not defect counts; every nonzero result was manually
classified.

| Marker | 2026-07-14 baseline | 2026-07-17 result | Classification |
| --- | ---: | ---: | --- |
| `wordpress_url` | 99 | 0 | Canonical site-field cutover is complete in active code/tests. |
| superseded connector markers | 17 | 36 | Blocking regression/unfinished cutover: 7 active `app` lines and 29 active tests still use `wp_ai_connector_runtime.v1`. |
| `blob_data` | 20 | 0 | Active media blob path removed. Historical migrations are outside this counter. |
| `_source_bytes_b64` / `_watermark_bytes_b64` | 4 | 0 | Internal runtime Base64 byte path removed; bounded provider-edge conversion remains separately allowed. |
| old public/playback token markers | 22 | 6 | One deny-projection field and five rejection/removal tests; no active old route or token truth was found. |

The superseded connector count above is the clean `22eff1e0` input revision.
The P5-A working tree adds one negative marker to
`test_refactor_target_contract.py` so the final raw working-tree count is 37:
7 active `app` lines, 29 pre-existing active-test lines, and 1 audit-owned
rejection marker. The extra static marker is not an accepted runtime contract.

Module-size observations:

| File | Baseline lines | Current lines | Interpretation |
| --- | ---: | ---: | --- |
| `app/domain/runtime/service.py` | 8,772 | 6,236 | Responsibilities have been extracted behind one facade; size alone is not phase-exit proof. |
| `app/api/routes/portal.py` | 3,864 | 4,574 | Security, serializers, and explicit-context work increased the file; raw growth is not automatically debt. |
| `app/api/routes/service.py` | 5,214 | 5,205 | Essentially unchanged by line count; P4 hot-path ownership was verified behaviorally. |

## Blocking Gaps

### P1 Connector Identity

The active public runtime uses `cloud_connector_runtime.v1` plus
`wordpress_operation.v1`, but hosted runtime profiles still expose and enforce
`connector_contract_version=wp_ai_connector_runtime.v1` in Admin service
models, catalog defaults, managed policy, and active tests. This contradicts
`CON-01`, `P1-E02`, `NO_COMPATIBILITY_LAYER`, and
`ONE_ACTIVE_CONTRACT_VERSION`.

Required resolution is an atomic contract batch: choose the one current
connector identity, update producers, consumers, Admin/frontend projections,
fixtures, tests, and current docs together, then prove the superseded active
marker search is empty. Do not preserve an alias or fallback.

### P1 Operator Evidence

`P1-E05` production title execution and `P1-E06` configuration/data
inventory-backup-restore are explicitly operator-only pending in the active
runbook. Local pytest or an older WordPress smoke cannot close them. Production
execution requires separate operator approval and secret handling under the
release policy.

### P2 Current WordPress Text Loop

Current automated contracts cover `title_generation`, `content_summary`, and
`content_rewrite`, with rewrite scoped to the selected source text. Existing
real WordPress records are historical or do not cover all of:

- the current `cloud_connector_runtime.v1 + wordpress_operation.v1` path;
- local review and apply for all three tasks;
- Cloud performing no WordPress write;
- idempotent replay and no duplicate local apply;
- auth, entitlement, provider, and idempotency-conflict failure evidence;
- explicit local/offline/privacy fallback posture.

### P5 Performance And Release Evidence

Existing hot-query, media-corpus, bounded-memory, media E2E, failure-drill,
bundle, and release-policy tools are reusable. They do not yet provide current
revision evidence for concurrent runtime load, queue bursts, long-running soak,
text-path latency, exact deploy-bundle replay, restore, or the final clean
six-repository matrix.

The canonical matrix repository is
`/Users/muze/gitee/npcink-workflow-toolbox`. Its default Cloud gate is only
`check:fast`; P5 must run `check:seam`, `check:perimeter`,
`check:anti-drift`, and `lint` separately.

## Security And Dependency Audit

### Release blockers

1. Python environment audit found eight known vulnerabilities in Pillow
   `12.2.0`; every advisory names `12.3.0` as the fix. Cloud decodes untrusted
   uploaded/provider image data, so this is not treated as an irrelevant
   transitive finding. The minimum isolated fix is `Pillow>=12.3,<13` plus a
   refreshed `uv.lock`, full dependency audit, focused media/security tests,
   and the representative corpus.
2. `admin_session_secret` is the first-choice root for both Admin session JWTs
   and persistent/runtime encryption purposes, including callback secrets,
   site signing material, Addon connection payloads, Portal idempotency
   responses, and runtime execution input. Provider-connection and service-
   setting secrets are already isolated under `service_settings_secret` and
   are explicitly outside this migration. The remaining reuse expands one
   compromise domain and makes ordinary Admin-session rotation able to strand
   durable ciphertext. Introduce a dedicated runtime-data encryption secret
   through an inventoried, backed-up, one-time re-encryption cutover; remove the
   temporary old-key read path before the batch exits. Do not keep a permanent
   dual-key compatibility fallback.

Pillow audit reproduction:

- UTC time: `2026-07-17T12:39:09Z`;
- environment: Python `3.12.10`, Pillow `12.2.0`;
- tool: `pip-audit 2.10.1`;
- command: `uvx pip-audit --path .venv/lib/python3.12/site-packages`;
- result: failed with eight findings, all fixed by `12.3.0`;
- advisory IDs: `PYSEC-2026-2253`, `PYSEC-2026-2255`,
  `PYSEC-2026-2257`, `PYSEC-2026-2256`, `PYSEC-2026-2254`,
  `PYSEC-2026-3453`, `PYSEC-2026-3451`, and `PYSEC-2026-3452`.

The tool also skipped the local unpublished project package
`npcink-ai-cloud==0.1.0`; that skip does not affect the Pillow finding and is
retained as an audit limitation.

### Follow-up hardening

- Root and frontend production `pnpm audit` reported no known vulnerabilities.
- The five WordPress repositories have no production Composer packages to
  audit; absence of packages is not a dev-tool or source-security assessment.
- Root and frontend lock synchronization currently checks dependency presence,
  not exact specifiers, resolved versions, peer graph, or overrides.
- Dependency audits are not release-blocking CI gates, and Dependabot entries
  currently set `open-pull-requests-limit: 0`.
- The reviewed secret-scan baseline still reports one private-key fixture in
  payment-gateway tests. It needs one precise fixture allowlist/baseline entry,
  not a broad private-key exclusion.
- `docker-compose.runtime.yml` binds the application to loopback, while
  `docker-compose.prod.yml` defaults port 8010 to all interfaces. The latter
  must bind loopback or be renamed/documented and guarded as a local build
  surface before release.
- Portal/Admin cookie JWT decoders should explicitly require their complete
  claim sets, matching the stricter bearer decoder, with missing-claim tests.
- A global sensitive-log regression gate remains absent. Authorization,
  cookies, provider URL queries, and secret-bearing fields need one bounded
  redaction contract.
- No independent penetration test, container-image CVE scan, production-config
  verification, or online-credential validation was performed in P5-A.

### Already covered

Existing focused tests and contracts cover HMAC body/timestamp/nonce/replay,
site and key status, Portal membership and selected-site isolation, Admin proxy
allowlisting before internal-token injection, durable Portal idempotency,
site-scoped media signed pull and ACK, bounded media validation, and default-off
fenced orphan cleanup. These controls reduce risk but do not waive the blockers
above.

## Cross-repository Snapshot

The read-only status snapshot used locally cached upstream information; no
fetch was performed.

| Repository | Revision | Branch | Status at snapshot |
| --- | --- | --- | --- |
| `npcink-abilities-toolkit` | `77321e8b4f75` | `master` | clean |
| `npcink-governance-core` | `af0e5128decb` | `master` | clean |
| `npcink-ai-client-adapter` | `60b90fa71ce5` | `master` | clean |
| `npcink-workflow-toolbox` | `2c75273cb717` | `master` | clean |
| `npcink-cloud-addon` | `b74d4c3c4a78` | `master` | clean |
| `npcink-ai-cloud` | `22eff1e0f455` | `codex/p4-portal-context-contraction` | clean before P5-A edits |

`composer quality:matrix` was used only for status inspection. The final
`composer quality:matrix:run -- --fail-on-dirty` remains pending until the
current Cloud batch is committed and all P1/P2 blockers are resolved.

## Provisional P5 Load Gate

The load harness does not yet exist. Its first implementation must use a
disposable local/staging environment and a deterministic fake provider by
default. Real-provider calls remain a small, separately approved smoke.

Initial provisional thresholds:

- unexpected HTTP 5xx, cross-site leakage, duplicate side effects, and
  non-governed WordPress writes: zero;
- accepted fake-provider run completion: at least 99%;
- provider-excluded API p95 at most 500 ms and p99 at most 1 s, with no
  regression greater than both 20% and 100 ms against the locked baseline;
- representative high-cardinality hot-query p95 at most 50 ms with required
  indexes and no unexplained full scan;
- steady queue-wait p95 at most two current poll intervals, with burst queues
  fully drained and no abnormal queued/running/dispatching residue;
- after warm-up, soak RSS growth at most 10%, with no monotonic FD or DB
  connection growth and artifact/queue counts returning to baseline;
- retain the accepted P3 media streaming, corpus, and maximum-image memory
  bounds unchanged.

These are engineering acceptance candidates, not production SLOs. Freeze them
only after three comparable local/staging baselines record dataset,
concurrency, duration, environment, revision, and complete warnings.

## Ordered Follow-up Batches

1. **P5-B1 connector cutover:** remove the active superseded connector marker
   atomically and rerun P1 searches and focused Cloud/Admin/Add-on contracts.
2. **P5-B2 security blockers:** update Pillow and separate runtime-data
   encryption through a backed-up one-time cutover, in separate reviewable
   commits.
3. **P5-B3 WordPress text acceptance:** package current components and prove
   title, summary, and selected-text rewrite through local governance.
4. **P5-B4 load/soak:** add the smallest deterministic harness, capture
   before/after API/query/queue/worker/memory evidence, and tune only measured
   bottlenecks in the existing stack.
5. **P5-B5 release closure:** run every Cloud/plugin gate, exact bundle replay,
   current media/text acceptance, restore rehearsal, clean central matrix,
   release-policy check, independent review, and the final requirement-to-
   evidence audit.

P5 remains incomplete until every blocker is closed or an explicit accepted
exception names its owner, scope, evidence, and rollback.

## Subsequent Batch Status

The phase table and findings above remain the authoritative snapshot of input
revision `22eff1e0f455`; they are not rewritten after the fact. The following
later engineering batches changed the current branch status:

| Batch | Current result | Evidence |
| --- | --- | --- |
| P5-B1 connector cutover | engineering complete | [P5-B1 Hosted Profile Contract Cutover](p5-b1-hosted-profile-contract-cutover-2026-07-17.md) |
| P5-B2 security blockers | engineering complete | [P5-B2 Security Hardening Closeout](p5-b2-security-hardening-2026-07-17.md) and [ADR-019](decisions/019-dedicated-runtime-data-encryption-domain.md) |
| P5-B3 WordPress text acceptance | engineering complete | [P5-B3 WordPress Text Acceptance Closeout](p5-b3-wordpress-ai-text-acceptance-2026-07-18.md): exact revisions and packages passed Fresh data-path, browser review/apply, deterministic offline, provider/run-metadata, package, six-repository matrix, and cleanup evidence; summary/rewrite equality remains an explicit provider-quality limitation, and this is not production or Core-audit approval |
| P5-B4 load/soak | pending | deterministic concurrent runtime, queue burst, query, worker, memory, and soak evidence remains required |
| P5-B5 release closure | pending | exact bundle, media/text replay, restore, complete security follow-ups, central matrix, release-policy proof, and final audit remain required |

P5-B2 removes the two release blockers recorded in **Security And Dependency
Audit**: Pillow is at the fixed floor with blocking default/Zilliz dependency
audits, and the five persisted runtime-data types use a dedicated fail-closed
encryption domain with an offline transactional cutover. This is engineering
evidence only. No production cutover, production approval, penetration test,
complete image CVE scan, or live-credential validation has occurred, and global
P5 remains incomplete.

P5-B3 closes only the current WordPress text contract/UI/write-loop acceptance
on its recorded revisions and package hashes. Its provider-quality limitation
is retained rather than rerun away; P5-B4 load/soak and P5-B5 release closure
remain pending, so global P5 is still incomplete.

## Current Resolution — 2026-07-19

This is an append-only current-status update. It does not revise the original
`22eff1e0f455` audit snapshot, its then-pending findings, or its historical risk
statements.

P5-B4 engineering acceptance passed at revision
`dff31baf942542d12860b82f6a65a47dd2129d91`. The complete evidence and
limitations are recorded in
[P5-B4 Runtime Load/Soak Closeout](p5-b4-runtime-load-soak-closeout-2026-07-19.md).
The formal runtime proof completed three independent fresh baselines, with all
`29/29` record gates passing in every baseline. Queue-wait p95 was `4.6318`,
`5.0296`, and `4.7298` seconds; transport failures and unexpected HTTP 5xx were
zero throughout. The formal high-cardinality hot-query proof and the current
media performance and representative-corpus replays also passed.

The earlier v4 single-worker result remains part of the evidence history: its
third baseline recorded a `10.0267`-second queue-wait p95 and failed the
10-second candidate threshold. That failure was not rerun away, and the
threshold was not lowered. The accepted proof instead used two proof-only
worker replicas to establish bounded queue capacity. Production and runtime
Compose defaults remain single-worker because multi-worker media concurrency
and heartbeat safety are not closed by this proof.

P5-B4 is engineering evidence only. It grants no production deployment or
release authorization. P5-B5 remains pending, global P5 release closure remains
incomplete, and no production release occurred. Temporary Docker dependency
resolution during the proof also exposed that the Dockerfile does not strictly
consume the repository lock file; that supply-chain issue is transferred to
P5-B5 for explicit closure rather than being hidden by the successful runtime
result.

### P5-B6 Production Topology Contraction

P5-B6 engineering acceptance passed at revision `fb58e354`. The evidence and
remaining operator boundaries are recorded in
[P5-B6 Production Topology Contraction Closeout](p5-b6-production-topology-contraction-closeout-2026-07-19.md).

The default release bundle no longer includes Caddy, Jaeger, or an
OpenTelemetry Collector. The external TLS Edge, loopback bundled NGINX, and
Gunicorn trust chain is explicit; the loader removes orphans and fails before
public health on any retired release-project service. Independent review's two
P1 findings were closed by a two-stage, rollback-aware Edge migration and a
private-key path that rejects permissive local modes and uploads only through a
random remote `0700` directory.

This closes the P5-B6 topology precondition only. The actual clean-tree image
scan/exact bundle, any governed CVE exception, WordPress text/media replay,
restore rehearsal, clean six-repository matrix, production operator evidence,
and final P0-P5 audit remain P5-B7/P5-B8 work. Global P5 and production release
authorization remain incomplete.

### P5-B7 Exact Release Bundle

P5-B7 engineering acceptance passed at revision `0663d95f`. The complete
artifact, scan, replay, failure-history, and limitation record is
[P5-B7 Exact Release Bundle Closeout](p5-b7-exact-release-bundle-closeout-2026-07-19.md).

The clean `linux/arm64` bundle SHA-256 is
`592d1ce23334cddf4a09db0f147d6db48aa1c696980adc24630ed333660baa17`.
Five exact image subjects passed the canonical scan and produced five archives
covering eight runtime roles. The same bundle passed pre-load and post-load
identity verification twice, fresh migration through Alembic head, seed,
health, live smoke, and isolated cleanup without changing the existing
development container set.

The API result includes exactly three allowlisted Python 3.14.6 High findings:
`CVE-2026-11940`, `CVE-2026-11972`, and `CVE-2026-15308`. Owner is `Muze`,
expiry is `2026-08-05`, and scope is engineering scan/bundle rehearsal only.
The original failed unallowlisted receipt remains failed and unchanged. This
exception is not production or GA authorization.

This closes the P5-B7 exact-image and exact-bundle engineering precondition
only. Current exact-package WordPress text/media replay, restore rehearsal,
all final Cloud/plugin gates, strict six-repository matrix, dependency
follow-up, production operator evidence, and the final P0-P5 audit remain
P5-B8 work. Global P5 and production release authorization remain incomplete.

### P5-B8 Final Engineering Closeout

This is an append-only current conclusion. It does not rewrite the original
`22eff1e0f455` audit snapshot or convert its historical findings into claims
about what was known at that time.

The P5-B8 code-owned/local engineering gate set is `passed` at Cloud
implementation HEAD `054ae3d81e7beb43523c12581f8764e80080855b`, and the
P0-P5 architecture is frozen. Global P5 and the overall refactor phase-exit
remain incomplete until the operator-only P1-E05/P1-E06 evidence exists. The
authoritative requirement-to-evidence table is
[P5-B8 Final Engineering Closeout](p5-b8-final-engineering-closeout-2026-07-19.md).
It records the exact WordPress packages, current local text/media replay,
performance, disposable restore drill, dependency follow-up, final Cloud and
five-plugin gates, strict six-repository matrix, rollback, and material
failed-first-path evidence.

The exact bundle is not relabeled as a `054ae3d8` artifact. It remains bound to
the last release-payload revision
`0663d95f765a8c49154aac0536e26cbb51029094`, SHA-256
`592d1ce23334cddf4a09db0f147d6db48aa1c696980adc24630ed333660baa17`.
The intervening changes contain only documentation, Dependabot configuration,
the release-policy checker, and its contracts; they contain no `app/**`,
`frontend/**`, Compose, deploy payload, or image-lock change.

The B8 text receipt records a real Save-and-Verify path, `6/6` Cloud runs,
three editor endpoint POSTs, zero pre-save writes, one explicit save, revision
delta `+1`, and cleanup. Its deterministic harness used a broad classifier that
sent all three requests through the rewrite branch, producing one shared UI
output hash. This is transport/UI/write-boundary evidence, not task-specific
semantic routing, model quality, or editorial-value evidence; P5-B3 retains the
task/profile and real-provider runtime metadata.

The B8 media receipt records `32` browser assertions and the governed round
trip through restore and cleanup. Its first plain-permalink run completed the
product requests but failed the harness pathname-owner assertion. The final
harness pass used a temporary index permalink and restored the original
permalink; the failed first result remains part of the record. The strict
matrix passed `6/6` with worktree dirty/ahead/behind `0`, while accurately
retaining one untouched pre-existing Cloud stash dated `2026-06-29`.

The local restore receipt is a synthetic representative graph, not a B8 live-
stack snapshot. It rejected corruption and a missing artifact, matched fresh-
restore database and artifact manifests, and removed all generated resources;
it does not prove production carry-forward, persistent/off-host backup, or
RPO/RTO.

Production promotion and GA remain blocked. P1-E05 production title execution
and P1-E06 production-like inventory/carry-forward/restore remain operator-only
and `production-only not claimed`. The three named Python 3.14.6 CVE exceptions
remain owned by `Muze`, expire `2026-08-05`, and apply only to the `linux/arm64`
engineering bundle. `linux/amd64`, production Edge/DNS/WAF/TLS/OTLP/secrets,
production backup/RPO/RTO, penetration testing, live-provider quality, and
real-user value are also `production-only not claimed`. External object storage
remains a deferred non-goal rather than a production prerequisite.
