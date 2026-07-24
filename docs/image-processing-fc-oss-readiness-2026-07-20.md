# Image Processing FC/OSS Readiness - 2026-07-20

Status: active time-bounded decision record and deferred
implementation-readiness note.

This note preserves the image-processing architecture, the July 2026
host-capacity observation, the decision not to migrate production image
processing to Alibaba Cloud Function Compute (FC), and the evidence needed
before that decision may change.

Current-authority note (2026-07-24): repository implementation facts and command
entries in this record were rechecked against revision `d32b03a2`. The host,
workload, pricing, and product-console observations remain dated
2026-07-20 evidence, not current procurement facts. ADR-022 subsequently moved
formal production database authority to a fresh external RDS PostgreSQL 18
installation; that change does not authorize FC, OSS, direct object upload, or
semantic-moderation rollout.

It does not supersede
[ADR-005](decisions/005-local-volume-artifact-store.md), authorize an OSS or FC
production rollout, change a public media contract, enable direct browser
upload, or approve production content-moderation policy.

## Decision Summary

The decision recorded on 2026-07-20 remains:

1. Keep the then-existing 2-vCPU/4-GiB ECS deployment, FastAPI API, PostgreSQL
   runtime truth, Redis wake-up signal, Python workers, and local-volume
   `ArtifactStore` for the current low-volume stage.
2. Do not migrate `image.transform.v1` to FC merely because the workload is a
   technically valid serverless candidate. The dated production evidence
   contains no recorded derivative jobs and therefore shows neither a capacity
   problem nor a real production image benchmark. Moving only the processor
   would also not remove the ECS fixed cost.
3. Keep FC as a future burst executor behind the existing runtime and artifact
   boundaries. It is a candidate for parallel derivative processing, not for
   replacing the Cloud API, PostgreSQL truth, Portal/Admin, WordPress review,
   or CMS write ownership.
4. Introduce private object storage and semantic content moderation before any
   open or direct user-to-object-storage upload path. File/MIME/decode safety is
   not a substitute for pornography, violence, political, illegal-content, or
   other policy review.
5. Reconsider the decision only after measured queue, batch, capacity,
   durability, recovery, or cost evidence crosses the candidate thresholds in
   this note.

For the host-sizing decision evaluated on 2026-07-20, the cost-first
2-vCPU/4-GiB class was the appropriate baseline. In the compared Alibaba Cloud
console options, the `u2a` 2-vCPU/4-GiB option was the least-cost candidate. A
newer compute-optimized family should be selected only when a fresh benchmark
or a service-level objective justifies its premium. Console prices and
available host CPUs are time- and region-dependent and must be rechecked before
any future purchase.

## Scope And Ownership Freeze

This note covers the existing typed derivative operation:

- request contract: `media_job_request.v1`;
- operation: `image.transform.v1`;
- source contract: `media_upload_request.v1` and temporary source artifact;
- result: short-lived derivative artifact delivered by signed pull and exact
  transfer acknowledgement.

It does not combine image transformation with image generation, alt-text vision
input, video processing, or a permanent Cloud media library.

Ownership remains:

- Cloud owns authenticated intake, technical validation, queued runtime
  execution, temporary artifact bytes, verified metadata, expiry/purge,
  transfer, usage, and diagnostic evidence.
- PostgreSQL `run_records` remains the durable runtime status/result truth.
  Redis, OSS events, EventBridge, FC invocation state, callbacks, and logs may
  be signals or evidence but must not become a second run truth.
- `ArtifactStore` remains the only business-facing byte-storage seam. Backend
  object keys, bucket names, native URLs, and credentials must not enter public
  media envelopes.
- WordPress/Core remains the permission, review, approval, preflight, import,
  association, replacement, rollback, publication, and canonical local audit
  owner.
- A delivery ACK proves verified transfer only. It never proves local review,
  import, attachment, replacement, or publication.

## Time-Bounded Host Evidence

An operator-authorized, read-only production host snapshot was taken on
2026-07-20. No address, password, domain, token, or deployment credential is
recorded in this document.

| Observation | Snapshot |
| --- | --- |
| Alibaba Cloud instance type | `ecs.e-c1m2.large` |
| Guest shape | x86_64, 2 vCPU, marketed 4 GiB memory |
| Presented CPU | Intel Xeon Platinum, model 85, about 2.5 GHz, KVM |
| CPU/load | about 94-98% idle across checks; load average `0.02 / 0.12 / 0.15` in the final sample |
| Memory | 3.5 GiB guest-visible, 1.3 GiB used, about 1.8 GiB available, no swap |
| Root disk | 40 GiB, 18 GiB used, 48% utilization |
| Runtime topology | 11 Cloud containers, up for 8-9 days |
| Stability | zero container restarts and no OOM-killed container in the snapshot |
| Runtime worker | about 79 MiB idle memory |
| Other examples | ops worker about 402 MiB, API about 191 MiB, PostgreSQL about 187 MiB |
| Runtime demand | 26 total runs, all succeeded; 1 run in the prior 24 hours; 0 queued and 0 running |
| Image derivative demand | 0 rows in `media_derivative_job_metrics`, including the prior 24 hours |

Interpretation:

- This is evidence that the host was lightly loaded at the inspection time, not
  a long-window capacity study or an SLA.
- There is no real production derivative workload in this snapshot. Existing
  local acceptance proves correctness and bounded behavior, but production
  image latency, throughput, and cost remain unmeasured.
- The vCPU brand string describes the backing host presented at that moment. A
  shared cloud instance family does not guarantee that exact physical model
  after host migration or repurchase. Instance family, vCPU/memory/network
  guarantees, and measured application behavior are more useful procurement
  inputs.
- Removing the roughly 79-MiB idle runtime worker would not by itself permit a
  safe ECS downgrade because the API, frontend, PostgreSQL, Redis, observability,
  callback, ops, and other runtime responsibilities remain.
- Before a future sizing decision, collect at least a representative production
  window rather than extrapolating from this snapshot.

## Implemented Image-Processing Flow

The repository lifecycle rechecked on 2026-07-24 is:

```text
WordPress/local host
  -> signed one-file upload
  -> Cloud technical validation
  -> local-volume source artifact + PostgreSQL metadata
  -> one typed image job per source
  -> PostgreSQL queued run + Redis wake-up signal
  -> ECS runtime worker + Pillow processor
  -> local-volume derivative artifact + metrics
  -> site-bound signed pull
  -> WordPress checksum/decode/review/governed write
  -> transfer ACK and independent TTL purge
```

Important implementation facts:

1. `POST /v1/runtime/media/uploads` accepts exactly one request and one file.
   It is not a 20-image or 100-image multipart endpoint.
2. Intake verifies the signed site request, declared MIME versus detected
   format, decodability, frame count, dimensions, pixel budget, server byte
   count, and SHA-256. Accepted bytes are stored once through `ArtifactStore`;
   PostgreSQL stores metadata, not image blobs or Base64.
3. `POST /v1/runtime/media/jobs` creates one queued
   `image.transform.v1` run for one source artifact. The queue input contains
   typed parameters and artifact references, never raw bytes or a storage key.
4. Batch planning uses `chunked_single_derivative_runs`. `batch_context` may
   describe up to 1,000 items, with a maximum chunk size of 20, but each image
   remains an independent upload/job/result. A 100-image request is therefore
   coordinated as multiple chunks of single-image runs rather than one giant
   function payload.
5. The production Compose topology at revision `d32b03a2` defines one runtime
   worker service. Its default drain size is eight runs per poll, but the loop
   processes those runs sequentially; the value is not eight-way image
   concurrency.
6. The processor supports max-width resize, aspect-ratio crop, text or image
   watermark, EXIF orientation correction, re-encoding with metadata stripping,
   and SHA-256 output verification. Targets are WebP, AVIF, JPEG, PNG, or the
   supported original still-image format.
7. Current limits include a 50-MiB source, 25-MiB deliverable result, 8,192
   pixels per axis, 16,777,216 decoded pixels, one static frame, and a 15-60
   minute artifact TTL with a 30-minute default.
8. The result is not returned as an ungoverned public object URL. WordPress
   pulls through the signed delivery contract, verifies locally, presents
   review, and performs any approved write through the local governance path.

The authoritative implementation and acceptance references are:

- [Media Runtime Boundary v1](media-runtime-boundary-v1.md)
- [Media Derivative Operations Runbook v1](media-derivative-operations-runbook-v1.md)
- [Cloud Media Delivery Boundary v1](cloud-media-delivery-boundary-v1.md)
- [WordPress Media Product Acceptance 2026-07-16](wordpress-media-product-acceptance-2026-07-16.md)

## Current Safety Posture And Missing Moderation Gate

Current technical safety is substantial but narrow. It protects the service
from malformed, oversized, mismatched, animated, cross-site, expired, corrupt,
or decompression-bomb-like inputs. It does not determine what the pixels depict.

Repository inspection on 2026-07-20 found no image-pipeline implementation of
semantic pornography, violence, political, illegal-content, or similar risk
classification. Existing references to comment moderation or generation policy
do not constitute uploaded-image moderation.

The current public media route is limited to provisioned, active, site-scoped
HMAC clients, so it is not an anonymous upload API. That lowers open-abuse risk
but does not remove platform, customer-content, complaint, takedown, retention,
or legal/compliance responsibilities.

Before direct browser-to-OSS upload, require all of the following:

- a private bucket; never public-read or public-write;
- a server-authorized upload intent bound to site, object prefix/key, content
  size, expiry, and idempotency identity;
- short-lived STS credentials limited to the minimum `PutObject` scope, with no
  bucket listing, arbitrary read, delete, ACL, lifecycle, or policy access;
- a quarantine prefix or bucket that cannot be downloaded through the normal
  result-delivery path;
- independent technical validation after upload; client MIME and filename are
  not trusted facts;
- semantic content moderation before transformation or delivery;
- bounded pass, reject, and manual-review policy with an explicit policy
  version, risk labels, confidence/evidence, and operator action;
- lifecycle deletion for abandoned, rejected, expired, and unreferenced
  objects, with bounded audit metadata but no raw image bytes or credentialed
  object URLs in logs;
- a takedown, suspension, key-revocation, and incident-response path appropriate
  to the production jurisdiction and product policy.

Do not attach the image-transform function directly to every object created in
the quarantine area. That would process and duplicate content before a policy
decision. If an OSS event trigger is used later, it should observe an approved
prefix/bucket or be gated by an explicit moderation-complete decision.

Alibaba Cloud references checked on 2026-07-20:

- [OSS content security detection](https://help.aliyun.com/zh/oss/user-guide/check-content-security)
- [OSS content security best practices](https://help.aliyun.com/zh/oss/oss-content-security-best-practices)
- [FC OSS trigger overview](https://help.aliyun.com/zh/functioncompute/fc/user-guide/overview-of-oss-trigger)

These product capabilities, supported regions, rules, and prices are external
facts and must be reverified before implementation.

## FC Suitability And Expected Benefit

`image.transform.v1` is a strong future FC candidate because it is bounded,
CPU/memory-sensitive, temporary, independently retryable by item, and naturally
bursty. The existing artifact-reference and typed-operation contracts already
provide a better migration seam than moving the whole Cloud service.

The expected gains are primarily batch throughput and workload isolation:

- A single image is not inherently faster in FC. It still runs the same
  decoder, crop/resize/watermark, and encoder code, while a cold instance may add
  startup latency.
- The current worker's processing time for `N` items is approximately the sum
  of the item times. With effective FC concurrency `C`, processor time trends
  toward `ceil(N / C)` waves, plus upload, moderation, scheduling, cold-start,
  object I/O, and result-collection overhead.
- A regular 20-image or 100-image burst can therefore benefit materially from
  parallelism even when individual-image latency does not improve.
- Isolating image work prevents large decode/encode bursts from delaying model,
  callback, or other runtime work on the ECS host.
- FC may avoid a future ECS upgrade made solely for intermittent image bursts.

The current reasons not to migrate are:

- measured production demand is almost absent and has no backlog;
- FC cannot read the current Docker shared volume, so an OSS-backed
  `ArtifactStore` or equivalent private object seam must exist first;
- the July snapshot's PostgreSQL and Redis endpoints were Compose-private;
  current formal production uses external RDS PostgreSQL 18 while Redis remains
  release-scoped, and FC would still need a deliberately designed private
  invocation/completion path rather than accidental database or public-service
  exposure;
- direct object upload requires a moderation and quarantine gate that does not
  exist today;
- the application host remains necessary for API, release-scoped Redis,
  frontend, observability integration, callback, ops, and non-image runtime
  work even though PostgreSQL is external RDS, so partial migration adds
  FC/OSS/moderation/logging cost without removing the fixed host bill;
- asynchronous invocation introduces duplicate/retry, timeout, stale-run,
  completion, observability, and rollback cases that must preserve existing
  idempotency and durable truth.

## Cost Model

FC compute can be inexpensive for occasional transformations, but low unit cost
does not imply immediate infrastructure savings.

As a dated illustration only, the Alibaba Cloud FC billing formula checked on
2026-07-20 charged active vCPU seconds, memory GB-seconds, and invocation count
through CU conversion. Assuming 1 vCPU, 2 GiB memory, and 2-5 active seconds per
image, 100 images were roughly 261-651 CU before other services. At the then
published first-tier list/promotional rates, that was approximately CNY
0.02-0.07 of FC compute.

This is not a quote or an end-to-end cost estimate. It excludes at least:

- hourly minimum billing behavior where applicable;
- OSS storage, request, retrieval, lifecycle, and transfer costs;
- content-moderation calls and manual review;
- logs, metrics, traces, EventBridge or other invocation paths;
- public egress and WordPress delivery;
- warm/minimum instances used to reduce cold starts;
- engineering, security review, incident response, and operation of two
  execution paths during canary and rollback;
- the retained ECS fixed cost.

Official pricing reference checked on 2026-07-20:
[FC billing overview](https://help.aliyun.com/zh/functioncompute/billing-overview-of-fc).
Recalculate from the then-current regional calculator before any purchase or
promotion decision.

The economic migration condition is not "FC per-image cost is small." It is:

```text
measured FC + OSS + moderation + observability + retained baseline cost
    < avoided ECS upgrade or other measured business cost
```

## Preferred Future Architecture

The preferred bounded target is:

```text
WordPress/local host
  -> Cloud-authorized upload intent
  -> private OSS quarantine object
  -> technical validation + semantic moderation
  -> approved source artifact
  -> normal Cloud job admission and run_records truth
  -> FC image.transform.v1 executor using artifact references
  -> private result artifact through ArtifactStore
  -> authenticated completion evidence
  -> existing site-bound signed pull
  -> WordPress local verify/review/governed write
  -> existing ACK, TTL, purge, and audit paths
```

Implementation rules:

- Preserve one image per typed run. Batch coordination may group item IDs and
  control concurrency, but must not put 20 or 100 binary images into one
  request, JSON field, database row, or function event.
- Invoke FC with a run ID, site-bound artifact IDs, contract version, and typed
  bounded parameters only. Do not send Base64 bytes, native storage keys,
  credentials, arbitrary URLs, or WordPress write decisions.
- Prefer an authenticated private execution/completion seam behind the current
  runtime service. Do not expose the Compose database directly merely to make
  the first FC proof easier.
- Keep `run_records` as durable truth and make invocation/completion idempotent.
  Duplicate object events or function retries must converge on one item result.
- Implement OSS behind `ArtifactStore`; runtime, processor, delivery, usage,
  and WordPress-facing services must not branch on or expose the selected
  backend.
- Keep the ECS worker as a controlled fallback during canary. A result may be
  completed by one execution backend only; fallback must use a claim/fence, not
  simultaneous best-effort processing.
- Preserve exact TTL, checksum, byte-size, site isolation, signed pull, ACK,
  purge, reconciliation, and orphan-cleanup safety semantics.
- Do not add a second workflow engine, customer media library, public bucket,
  or Cloud-side CMS apply/publish surface.

## Staged Implementation Path

### Stage 0: Observe And Freeze Current Truth

- Keep ECS/local-volume processing as the production path.
- Collect real image-job count, queue wait, processing p50/p95, batch wall time,
  source/output bytes, worker CPU/RSS, failure codes, artifact bytes, and
  delivery completion/ACK evidence.
- Define the product batch SLO before declaring the current worker slow.
- Keep pricing observations date-stamped and non-authoritative.

### Stage 1: Object-Storage Adapter Without Direct Upload Or FC

- Implement an OSS-backed `ArtifactStore` behind the current interface.
- Initially keep API-mediated upload and the ECS worker so storage behavior is
  the only changed variable.
- Prove atomic/uncertain publication handling, bounded streaming, metadata,
  checksum, expiry, purge, inventory reconciliation, orphan isolation, site
  isolation, and rollback to local volume.
- Do not expose OSS URLs or keys and do not enable public bucket access.

### Stage 2: Quarantine And Moderation Pilot

- Add authenticated upload-intent and least-privilege STS issuance only after
  the threat model and policy are approved.
- Route new objects to private quarantine.
- Run technical validation and semantic moderation; only approved objects may
  become available source artifacts or create image jobs.
- Prove rejection, expiry, cleanup, replay, cross-site denial, operator review,
  suspension, and takedown behavior.
- Do not check real prohibited content into repository fixtures. Use provider
  test cases, synthetic labels, or separately governed test assets.

### Stage 3: FC Execution Proof

- Package the same bounded processor and encoder dependencies for FC.
- Benchmark ECS versus at least 1-vCPU/2-GiB and 2-vCPU/4-GiB FC configurations.
- Use the existing representative corpus plus fixed 20-item and 100-item
  batches, including JPEG, PNG alpha, WebP, EXIF orientation, crop, image/text
  watermark, WebP output, explicit AVIF, invalid input, and oversized rejection.
- Keep output correctness, metadata stripping, checksum, site isolation,
  idempotency, and failure contracts equal to the ECS path.
- Measure cold and warm invocation separately.

### Stage 4: Bounded Canary

- Add an explicit task-backend selection owned by the Cloud runtime, not a new
  WordPress setting or workflow registry.
- Enable FC for one internal site or a bounded percentage while retaining the
  fenced ECS fallback.
- Compare all-in cost, queue wait, processing p95, batch wall time, failure and
  retry rates, moderation latency, delivery success, and operator burden.
- Roll back to the ECS executor on contract drift, cost regression, moderation
  bypass, stale-run growth, or recovery uncertainty.

### Stage 5: Production Decision

- Write a new ADR if FC becomes the accepted production executor or OSS becomes
  the accepted production artifact backend.
- Reverify current Alibaba Cloud regions, limits, prices, data handling, and
  content-security behavior.
- Run the full affected-repository acceptance matrix and real WordPress flow.
- Promote only through the repository production-release policy. This note is
  not inherited production approval.

## Candidate Reconsideration Triggers

These are proposed evidence triggers, not accepted product SLOs. Ratify them
with real user expectations before using them as a release gate.

Start a formal FC proof when one or more are true:

- real 20-item or 100-item batches become regular rather than hypothetical;
- image-job queue-wait p95 repeatedly exceeds about 10 seconds or the agreed
  product SLO over a representative sample;
- batch wall time fails the agreed user SLO even though individual processing
  remains correct;
- image work keeps worker/host CPU above about 70% for a sustained interval,
  causes material memory pressure, or delays unrelated runtime work;
- the next ECS size increase would be required primarily for intermittent image
  bursts;
- an all-in FC proof shows a meaningful throughput/SLO gain and costs less than
  the avoided capacity or business impact.

Start a formal OSS backend decision independently when one or more ADR-005
categories are true:

- projected artifact volume exceeds local capacity or backup window;
- API and workers must span hosts without a safe shared filesystem;
- required durability, recovery time, or recovery point exceeds the documented
  local-volume backup and restore capability.

Semantic moderation is not conditional on FC load. It is a prerequisite for
direct user-to-object-storage upload and should be implemented when that ingress
model is introduced, even if image transformation remains on ECS.

## Benchmark And Acceptance Record

A future proof should record, for every tested executor/specification:

| Dimension | Required evidence |
| --- | --- |
| Dataset | file count, formats, dimensions, encoded bytes, pixel budget, crop/watermark/format mix |
| Runtime | exact source commit, container/package digest, Pillow and encoder versions, region and specification |
| Latency | upload, moderation, queue wait, cold start, processing p50/p95, result publication, pull, full batch wall time |
| Capacity | effective concurrency, scale-up behavior, throttling, worker/instance CPU and peak RSS |
| Correctness | dimensions, MIME, decode, alpha/orientation behavior, metadata removal, byte size, checksum, warnings |
| Reliability | duplicate invocation, timeout, retry, stale run, partial write, completion replay, fallback fencing |
| Security | private storage, scoped STS, cross-site denial, no native URLs/keys, moderation fail-closed behavior |
| Lifecycle | TTL, ACK semantics, purge, inventory, orphan handling, rejected/quarantined cleanup |
| Cost | FC, OSS, moderation, logging/metrics, EventBridge/invocation, egress, retained ECS, operator time |
| Product | 20/100-image user-perceived time, preview/review, Core proposal, local write, rollback and audit |

Minimum repository gates for an implementation batch should include the
narrowest applicable subset and report exact outcomes:

```bash
pnpm run check:media:corpus
pnpm run check:media:staging
pnpm run check:fast
pnpm run check:seam
pnpm run check:perimeter
pnpm run smoke:media-derivative:wp
```

If WordPress repositories or public contracts are touched, run the canonical
cross-repository matrix from `/Users/muze/gitee/npcink-workflow-toolbox` before
closeout. A local or FC benchmark alone is not production or CMS acceptance.

## Development Lessons

1. **Measure before rewriting infrastructure.** A technically elegant
   serverless fit is not a product bottleneck. The July host had large CPU and
   memory headroom, almost no runtime demand, and no recorded derivative jobs.
2. **Separate single-item latency from batch throughput.** FC mainly changes
   concurrency and isolation. It does not automatically make Pillow encode one
   image faster.
3. **Count retained fixed cost.** Moving one worker does not save the ECS bill
   while API, databases, frontend, and other workers remain.
4. **Move bytes before compute.** Remote compute cannot consume the current
   shared Docker volume. A backend-neutral, verified storage seam must precede
   FC execution.
5. **File safety is not content safety.** MIME, magic, decode, dimensions, and
   checksum protect technical integrity; they do not classify pornography,
   violence, or other prohibited content.
6. **Use many bounded items, not one giant batch payload.** Per-image runs make
   limits, retries, idempotency, progress, failure isolation, and billing
   evidence tractable.
7. **Keep event systems as signals.** Redis, OSS triggers, EventBridge, and FC
   callbacks can wake or complete work, but PostgreSQL remains durable truth.
8. **Preserve the CMS boundary during optimization.** Faster Cloud processing
   must not acquire WordPress approval, write, publication, or local audit
   ownership.
9. **Design moderation before direct upload.** Do not create a public bucket or
   transform quarantine objects while governance is still undefined.
10. **Prefer a reversible seam and a canary.** Storage backend, execution
    backend, and direct-ingress changes should be isolated, feature-bounded,
    measured, and independently rollbackable.
11. **Treat provider pricing and host branding as dated evidence.** Recheck
    region availability, SKU, CPU guarantees, FC billing, OSS fees, and content
    security before a future purchase or rollout.

## Decision Reopening Rule

This decision may be reopened with a short evidence package containing:

- the real workload window and product SLO;
- current ECS capacity and the specific avoided upgrade;
- 20-item and 100-item ECS/FC benchmark results;
- all-in regional cost, not FC compute alone;
- approved private-storage and content-moderation design;
- idempotency, recovery, fallback, and rollback proof;
- confirmation that Cloud/WordPress ownership remains unchanged.

Until that package exists, the default remains the current ECS worker and
local-volume `ArtifactStore`.

## Related Records

- [ADR-005: Cloud-managed local-volume ArtifactStore](decisions/005-local-volume-artifact-store.md)
- [ADR-022: One-Time Cloud Install and Fresh RDS PostgreSQL 18](decisions/022-one-time-cloud-install-and-rds-postgresql-18.md)
- [Runtime Stack Decision History - 2026-07-09](runtime-stack-decision-history-2026-07-09.md)
- [Media Runtime Boundary v1](media-runtime-boundary-v1.md)
- [Media Derivative Operations Runbook v1](media-derivative-operations-runbook-v1.md)
- [Cloud Media Delivery Boundary v1](cloud-media-delivery-boundary-v1.md)
- [Media Runtime B5 Closeout 2026-07-16](media-runtime-b5-closeout-2026-07-16.md)
- [WordPress Media Product Acceptance 2026-07-16](wordpress-media-product-acceptance-2026-07-16.md)
