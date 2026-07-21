# Media Runtime Boundary v1

Status: P3-B4D complete with real WordPress and Cloud evidence (2026-07-16).
P3-B5 media closeout is also complete with exact-package, fresh-environment,
performance, security, recovery, matrix, and independent-review evidence.
Persistent orphan cleanup remains production/default-off.

## 1. Purpose

Define the WordPress-first Media Runtime boundary for temporary, streamed,
site-scoped media processing in Npcink AI Cloud.

Cloud may ingest bytes, run a typed hosted media operation, retain a temporary
artifact, and expose a signed pull. WordPress remains the owner of local
permissions, verification, review, approval, media-library writes, object
assignment, publication, and local audit.

This document began as the P0 target contract. Section 3 records the implemented
P3-B1 byte-store foundation, P3-B2 streamed ingress, P3-B3A upload/image-job
resource split, P3-B3B1 image-generation artifact convergence, and P3-B3B2
artifact-referenced vision input, P3-B4A lifecycle projection, P3-B4B1 signed
pull/delivery ACK, P3-B4B2 legacy-route/permanent-audio-asset removal, P3-B4B3
unified delivery observability, P3-B4C1a publication compensation,
P3-B4C1b fenced TTL purge/delivery coordination, P3-B4C2a read-only inventory
reconciliation/publication fencing, P3-B4C2b persistent default-off orphan
cleanup, and the P3-B4C3 isolated PostgreSQL 16 multi-connection/named-volume
proof. P3-B4D is complete: the fail-closed smoke passed against the real local
WordPress chain and the live development Cloud on 2026-07-16. The accepted run
was `run_ea365c8ef6fb4b1dbe721338208d9aee`, with derivative artifact
`art_9ea7725f20914e819ba17d7d2ecc60ff` and explicit receive delivery
`mdl_ae8fc3d7e06c49fc90d1872314323e50`. P3-B5 subsequently completed the exact
package and fresh-environment release validation recorded in
[Media Runtime B5 Closeout 2026-07-16](media-runtime-b5-closeout-2026-07-16.md).
Production cleanup remains disabled. P3-B5 is a bounded media milestone, not
the global P5 refactor milestone and not authorization to enable production
orphan cleanup.

Toolbox remains the real WordPress operator entry for media derivatives. The
B4D smoke intentionally bypasses presentation code and calls only the stable
Addon PHP transport seams plus Adapter generic read and Core proposal paths so
it can freeze the cross-layer contract. It does not recreate an Adapter-owned
media run, result, preview, or proposal-payload facade.

## 2. Stable Markers

- `TEMPORARY_MEDIA_RUNTIME`: Cloud artifacts are temporary runtime outputs, not
  a media library.
- `STREAMED_MEDIA_BYTES`: uploads, provider fetches, and downloads use bounded
  streaming rather than whole-object buffering.
- `DELIVERABLE_ARTIFACT_LIMIT`: source uploads may be larger, but every
  temporary derivative must be at most 25 MiB so the current connector contract
  can consume it; oversized encoder output fails before artifact publication.
- `NO_DATABASE_BLOB`: relational runtime truth stores artifact metadata only.
- `SIGNED_PULL`: a site obtains its result through a short-lived, site-bound
  signed pull; Cloud does not push bytes to a caller-supplied URL.
- `LOCAL_MEDIA_WRITE`: WordPress owns final validation, review, media import,
  attachment changes, assignment, publication, and audit.

## 3. Current Evidence And Target State

Current repository evidence includes a hosted runtime, authenticated site
scope, durable run evidence, queue workers, provider routing, usage and
entitlement checks, diagnostics, and existing media-oriented work. That
evidence supports the direction but does not prove this target contract.

P3-B4B2 removed the legacy authenticated derivative download, public-token
download, permanent audio-asset model/router/configuration, and their dead
derivative download counter writer. P3-B4C1b replaces the old in-transaction
cleanup helper with one leased `MediaArtifact` TTL purge and coordinates purge,
stream completion, and ACK on one artifact-first lock order. P3-B4C2a adds
bounded, read-only store-versus-database inventory evidence. P3-B4C2b adds
durable complete-pass/candidate truth, fixed-root publication sessions, and
per-candidate fenced orphan deletion, with runtime/deployment configuration
defaulting to disabled. Historical database blob paths,
request/result Base64 media payloads, and audio-specific download-token shapes
are migration history, not contracts to preserve.

The target state is one `TEMPORARY_MEDIA_RUNTIME` that serves typed operations
through the existing Cloud runtime foundation. It uses one metadata envelope,
one pluggable byte store, one site-isolated delivery model, and no second
runtime or WordPress control plane.

P3-B1 originally provided the metadata-only `MediaArtifact`, a local-volume
`ArtifactStore`, bounded artifact streams, independent permanent audio-asset
objects, and byte-first purge. P3-B4B2 supersedes its temporary compatibility
posture by deleting the independent audio-asset and legacy delivery surfaces.

P3-B2 converted the former `POST /v1/runtime/media-derivatives` seam from whole-body buffering
and one-shot multipart parsing to a bounded signed ingress:

- required auth headers, nonce, idempotency key, signature syntax, and timestamp
  freshness are checked before the body evidence loader is allowed to receive
  a large body. A short-lived database preflight also verifies the active site,
  active key, and required scope, then closes before body reception;
- the loader treats `Content-Length` only as an early bound, counts actual
  streamed bytes as authoritative, writes them to one `TemporaryFile`, and
  computes SHA-256 during the same pass;
- the sealed size/digest evidence is validated by the existing HMAC canonical
  request. Parsing starts only after authentication succeeds and replays the
  exact same sealed temporary file; the route never reads the network body a
  second time. A new current time and a new database session revalidate the
  timestamp, site, key, and scope after capture, so upload-time revocation wins
  without holding a database connection during the upload;
- JSON and the multipart `request` field are bounded to 64 KiB. Multipart is
  bounded to one field, two files, 16 KiB of headers per part, and only
  `request`, `source_file`, and `watermark_file`; duplicate, unknown,
  incomplete, or type-masquerading parts fail closed;
- each upload file remains capped at 50 MiB. Starlette's 1 MiB spool threshold
  moves larger file parts to disk before the authenticated route materializes
  an accepted source or watermark once for the existing B2 service seam;
- the raw capture, published and incomplete multipart spools are closed after
  success, auth rejection, parse/validation failure, storage failure, service
  exception, or cancellation. Temporary-file create/write/short-write and
  multipart spool create/read failures return a stable 503
  ingress-unavailable result;
- exact Nginx locations permit 52 MiB only for this route, retain the existing
  upstream and public-runtime timeout/rate semantics, and add a dedicated
  per-client request and two-connection limit plus an eight-connection
  route-wide budget. Limit rejections return 429 and global body limits remain
  unchanged. In production, the operator-owned TLS Edge replaces inbound
  client-address and forwarded headers before reaching the loopback NGINX
  ingress. Runtime Compose pins its gateway to `172.28.0.1`; NGINX accepts
  `X-Real-IP` only from that gateway, so `$binary_remote_addr` continues to
  represent the verified client for per-client zones, and sends
  `X-Forwarded-For $remote_addr` upstream instead of appending an untrusted
  chain. NGINX is separately pinned to `172.28.0.10`, the only forwarded proxy
  address trusted by Gunicorn. The loopback local-development direct-client
  path does not rewrite client addresses. The local exact-bundle HTTP smoke is
  an explicit loopback-only exception and is not a production ingress model.

This deliberately performs two disk I/O passes for multipart requests:
network to the sealed raw spool, then raw spool to bounded multipart file
spools. The extra pass preserves auth-before-parse error ordering, binds the
signature to the bytes that are parsed, and keeps application memory bounded.
It did not create a second runtime, CMS write path, or control-plane truth.

P3-B3A atomically replaces that pre-GA public POST route with two resources:

- `POST /v1/runtime/media/uploads` accepts exactly one `request` field and one
  `file`. It preserves P3-B2 auth-before-parse, sealed body evidence, 52 MiB
  proxy/51 MiB application limits, 50 MiB file limit, disk spooling, stable
  429/503 behavior, and cleanup ownership. It validates declared MIME against
  detected format, Pillow verification and decode, an 8,192-pixel per-axis
  ceiling, a 16,777,216-pixel/64 MiB RGBA decode budget, frame count, server
  byte count, and SHA-256 without materializing the whole upload as Python
  `bytes`. The accepted stream is stored once and creates a
  synchronous, zero-credit `media_upload_request.v1` run plus an available
  `image.upload.v1` source artifact;
- upload runs remain visible in runtime operational totals but are classified
  as non-AI, zero-credit evidence. Provider-call and usage-meter coverage
  denominators and alerts include only runs that require AI evidence;
- `POST /v1/runtime/media/jobs` accepts `media_job_request.v1` with the
  versioned `image.transform.v1` operation, source/watermark artifact IDs,
  strict transform parameters, optional batch context, and result TTL. It
  validates same-site available image artifacts and requires their remaining
  TTL to cover the execution timeout before queue admission;
- queued run input contains only artifact references and typed parameters in
  `input_json` and encrypted execution input. It contains no byte payload,
  Base64 field, or `storage_key`. The worker revalidates site, type, lifecycle,
  byte size, checksum, and expiry, then performs one bounded read at the current
  processor seam. Result metadata uses `image.transform.v1`;
- upload idempotency verifies the typed request and server checksum before any
  repeat put. A missing/expired/corrupt replay artifact fails closed. Image-job
  replay is checked before queue capacity and new-job TTL admission;
- the former POST route has no compatibility alias. P3-B4B2 later removed the
  legacy authenticated artifact download and audio public-token download;
  neither is part of the signed-pull contract.

P3-B3A still uses two disk I/O passes at ingress and may materialize one bounded
source plus watermark inside the Pillow worker because the current processor
accepts `bytes`.

P3-B3B1 atomically replaces provider-media image-generation results with
artifact-only results:

- `image_generation_request.v1` accepts bounded generation intent only. It
  rejects caller-selected `response_format`, URL, Base64, data-URL, fetch,
  provider transport, unknown, secret, and CMS-write fields. The old `text`
  prompt alias is absent; prompt, count, aspect ratio, and resolution use exact
  scalar types without coercion; and `storage_mode=no_store` is invalid because
  the generated bytes must become a temporary artifact;
- provider adapters return a typed, non-JSON `ProviderMediaCandidate` carrying
  exactly one transient URL or strictly decoded byte source. Generic provider
  output contains neither source, provider payload, old result shape, nor
  WordPress posture fields;
- a URL-returning provider requires exact connection-owned
  `image_output_hosts`. The private fetch accepts HTTPS port 443 only, rejects
  credentials, fragments, redirects, private/non-global DNS answers, and
  environment proxies, then connects to an approved IP while preserving the
  original Host and TLS SNI. One hard deadline covers DNS through the complete
  stream, only eight workers may be admitted per process, and late results are
  discarded and closed. Actual streamed bytes are bounded. HTTP client request
  logs are suppressed below WARNING so signed provider query strings do not
  enter application logs;
- source and sanitized output bytes share one 64 MiB run I/O budget, with a
  24 MiB per-image ceiling and four-candidate limit. MIME, magic, full decode,
  one frame, 8,192-pixel axes, 16,777,216 total pixels, and provider dimension
  claims are checked before EXIF orientation and metadata-stripping re-encode;
- sanitized output creates `MediaArtifact(operation=image.generate.v1)` under
  the current run/site with verified storage facts and a 30-minute TTL. A batch
  is all-or-nothing. Ordinary savepoint, outer transaction, normalization, and
  run-finalization rollback cleans published objects. P3-B4C1a routes all
  active artifact producers through one transaction tracker; a DBAPI commit
  whose outcome cannot be proven moves its publications out of active rollback
  cleanup and into a deduplicated Session-local in-memory no-delete quarantine.
  Rollback-cleanup delete failures quarantine only the failed keys before
  raising. This tuple is not persistent evidence and has no production
  consumer. P3-B4C2a instead uses a bounded artifact-store inventory versus
  database inventory scan after a safety window, without deleting observations.
  The generic tracker resolves only the outer transaction;
  image generation is the only current nested-savepoint producer and retains
  explicit cleanup, successful-delete forgetting, and failed-delete quarantine;
- `image_generation_result.v1` contains artifact references, validated media
  facts, `suggestion_only=true`, and `requires_local_review=true`. Download URL,
  provider URL, Base64, raw response, `storage_key`, and WordPress write fields
  are absent.

P3-B3B2 atomically replaces URL/data-URL WordPress alt-text vision input with
one required `source_artifact_id`:

- resolve and new execute metadata admission require a same-site, available,
  unpurged, unexpired JPEG, PNG, or WebP artifact within the 8 MiB vision
  budget; cross-site IDs are indistinguishable from missing IDs;
- execute checks idempotent replay before current artifact admission, so a
  completed result remains replayable after the source expires;
- sync and queued provider execution revalidate the artifact and perform a
  bounded size/checksum-verified store read immediately before provider
  preparation;
- only the private provider edge constructs a transient data URL. Public and
  durable contracts use an exact canonical field allowlist and recursively
  reject URL, caller MIME, data URL, raw Base64, bytes, storage keys, field
  aliases, and case/whitespace variants. Allowed values use a strict bounded
  scalar schema rather than string or integer coercion, so nested transports
  fail before run creation and queue encryption. Provider request
  representations and canonical vision errors prevent the transient source
  from leaking through ordinary diagnostics;
- successful provider output is projected to bounded `output_text` only. Raw
  and nested provider fields are discarded, and output text containing inline
  media transport fails closed instead of entering result or callback truth;
- the default data classification is `internal`, and the result remains a text
  suggestion. WordPress still owns attachment choice, review, metadata write,
  and local audit.

Historical run-result metadata remains a creation-time snapshot. P3-B4A now
projects current `expired`/`purged` state across run-result reads, execution
responses, idempotent replay, and delayed callbacks without rewriting that
snapshot. P3-B4B1 adds nonce-protected same-site HMAC pull, dedicated
`public_pull_*` replay/rate/rejection scopes, exact metadata preflight,
non-buffered verified streaming, independent `MediaArtifactDelivery` evidence,
and strict idempotent transfer ACK that records receipt without changing the
artifact's original bounded expiry.
Known media projections remove historical URL/token/Base64 fields without
rewriting durable results. P3-B4B2 removes the legacy routes, token helpers,
permanent audio-asset surface, and active table. P3-B4C1b implements fenced TTL
purge and delivery coordination. P3-B4C2a adds the independent read-only
inventory scanner and aggregate cadence evidence. Persistent orphan deletion
and broader media kinds remain later work.

The three B4A public projection outlets are run-result reads; initial,
transient, and idempotent execution responses; and delayed terminal callback
payloads. The durable creation-time snapshot is never rewritten by projection.
Projection recognizes only four exact type/version marker pairs:
`media_upload_artifact` / `media_upload_result.v1`,
`media_derivative_artifact` / `media_derivative_result.v1`,
`image_generation_artifacts` / `image_generation_result.v1`, and
`audio_generation_candidates` / `audio_generation_result.v1`. Missing or
unknown markers are unrelated result JSON and remain untouched.

## 4. End-to-End Lifecycle

The required lifecycle is:

```text
ingest -> validate -> queue -> process -> artifact -> signed pull
       -> local verify/review/write -> delivery ack/purge
```

1. **Ingest:** Cloud authenticates the provisioned site and streams an upload
   into temporary storage under hard transfer limits.
2. **Validate:** Cloud verifies declared type, magic bytes, decodability,
   dimensions, frame count, byte size, and checksum before accepting the source.
3. **Queue:** Cloud creates a site-scoped job for one approved typed operation.
4. **Process:** A worker reads the source through `ArtifactStore`, invokes the
   selected typed processor, and streams the result back to the store.
5. **Artifact:** Cloud records result metadata and a bounded expiry time; no
   binary result enters relational runtime truth.
6. **Signed pull:** WordPress sends a site-bound HMAC request with a dedicated
   one-time nonce and streams the artifact from Cloud.
7. **Local verify/review/write:** WordPress verifies the bytes and checksum,
   rechecks permissions and local object state, presents review, and performs
   any approved local media write.
8. **Delivery ack/purge:** WordPress may acknowledge completed transfer. The
   acknowledgement records receipt without changing the original bounded TTL;
   idempotent purge still follows that expiry.

A delivery acknowledgement means only that delivery completed. It never means
that WordPress reviewed, approved, imported, attached, assigned, or published
the artifact.

## 5. Target Resources And State Model

Resource status is:

- `POST /v1/runtime/media/uploads`
  - **implemented in P3-B3A**; streams one site-scoped source artifact into
    temporary storage;
- `POST /v1/runtime/media/jobs`
  - **implemented in P3-B3A**; creates one queue-backed job for one approved
    typed media operation;
- `GET /v1/runtime/media/artifacts/{artifact_id}/download`
  - **implemented in P3-B4B1**; verifies a nonce-protected signed pull, records
    delivery start/completion evidence, and streams the exact site-scoped
    artifact without response buffering;
- `POST /v1/runtime/media/artifacts/{artifact_id}/delivery-ack`
  - **implemented in P3-B4B1**; records verified transfer acknowledgement only
    without changing the artifact TTL.

The logical resource relationships are:

```text
authenticated site -> upload artifact -> media job -> result artifact
                   -> signed pull -> delivery acknowledgement -> purge
```

Job state is separate from artifact state. A minimal job progression is
`queued -> processing -> succeeded|failed|canceled`. An artifact progresses
through `pending -> available -> expired -> purged`, with `failed` available
for validation or storage failure. Retry must not duplicate a source, job, or
result for the same site-scoped idempotency identity.

`run_id` correlates the media job with hosted run evidence. `run_records` may
reference artifact identifiers and bounded metadata, but it is not an artifact
byte store or a second media state machine.

## 6. MediaArtifact Metadata Contract

`MediaArtifact` stores metadata only. Its target fields are:

| Field | Required meaning |
| --- | --- |
| `artifact_id` | Server-generated opaque artifact identity. |
| `site_id` | Owning authenticated site and authorization scope. |
| `run_id` | Correlated hosted run or media job evidence. |
| `media_kind` | Typed media family, with `image` first. |
| `operation` | Approved versioned typed operation contract. |
| `content_type` | Validated output media type, not trusted input alone. |
| `byte_size` | Count of bytes written to the artifact store. |
| `checksum` | Server-computed digest, using SHA-256 for P3. |
| `storage_key` | Internal opaque byte-store locator, never a public URL. |
| `status` | Artifact lifecycle state. |
| `created_at` | Server creation timestamp. |
| `expires_at` | Server-enforced purge eligibility timestamp. |

The artifact envelope must never contain binary bytes. Media bytes must not be
stored in PostgreSQL blobs, JSON or Base64 request/result fields, audit events,
logs, or `run_records`. API responses return identifiers, metadata, status,
expiry, and bounded delivery facts only.

## 7. ArtifactStore Boundary

Business services depend on a minimal byte-storage interface equivalent to:

```text
put(stream, metadata) -> storage result
open(storage_key) -> readable stream
delete(storage_key) -> idempotent outcome
metadata(storage_key) -> bounded storage facts
```

`put` and `open` must preserve `STREAMED_MEDIA_BYTES`. Implementations enforce
bounded chunks and must not require a complete object in application memory.

The first implementation uses a Cloud-managed local volume. PostgreSQL stores
the `MediaArtifact` metadata; the volume stores only bytes. Temporary and final
paths must support atomic publication so incomplete output cannot become an
available artifact.

An S3-compatible backend may replace the local volume only after measured need
crosses a capacity, multi-instance, or durability threshold. Examples include
the volume capacity forecast exceeding its operating budget, workers spanning
hosts that cannot share the volume safely, or a required durability objective
that local storage cannot meet.

The backend switch occurs behind `ArtifactStore`. Runtime, processor, delivery,
usage, and WordPress-facing services must not branch on local-volume versus
S3-compatible storage or expose backend-native keys and URLs.

## 8. Operation Contracts

Image processing and image generation are different typed operation contracts.
They share the same site, run, artifact, storage, delivery, expiry, and
observability envelope, but not one permissive input schema.

- An image-processing contract identifies source `artifact_id`, a versioned
  transform operation, and bounded operation-specific parameters such as size,
  crop, or output format.
- An image-generation contract identifies a versioned generation operation,
  bounded generation inputs, provider/model execution evidence, and output
  constraints. It does not grant arbitrary remote fetch or CMS write authority.

Each processor must declare accepted content types, input and output limits,
parameter schema, timeout, retry posture, and deterministic or non-deterministic
idempotency behavior. Unknown `media_kind`, `operation`, or parameter fields
fail closed.

The target operations on the four resources are:

- upload: authenticate, stream, validate, checksum, and create source metadata;
- create job: validate a typed contract and enqueue one idempotent job;
- download: authorize a site-bound signed pull and stream verified bytes;
- delivery ack: record delivery completion without recording local apply state.

The first implementation must not introduce a universal media DAG, arbitrary
instruction processor, user-defined pipeline, or general workflow engine.

## 9. Security And Isolation

The implementation must fail closed and apply all of these controls:

- Enforce hard byte limits while streaming uploads, provider downloads, and
  processor outputs. `Content-Length` is only an early hint; counted bytes are
  authoritative.
- Require agreement among allowed MIME, magic bytes, and successful decode.
  A filename extension or caller-declared type is never sufficient.
- Enforce image dimensions, total pixel count, and frame count before
  processing. Reject decompression bombs and unsupported animated inputs.
- Compute and persist SHA-256 checksums while streaming. WordPress verifies the
  returned size and checksum after pull.
- Strip EXIF and GPS metadata by default from generated or transformed output.
  No metadata-preserving override is part of the first image contract.
- Scope every artifact lookup, job, signed authorization, store access, metric,
  and purge action to the authenticated `site_id`.
- Prevent SSRF. Client-supplied arbitrary fetch URLs are not media inputs.
  Provider-result fetches use an explicit provider host allowlist, public-IP
  checks, redirect limits, DNS revalidation, timeouts, byte budgets, and rate
  budgets.
- Treat provider URLs as temporary transport references, never as trusted
  content or durable artifact identities.
- Reject executable or active content. Image contracts do not accept HTML,
  script, executable archives, or active SVG as decoded image output.
- Accept only timestamp-bounded HMAC pulls bound to the site, artifact path, and
  a one-time nonce. Do not mint download credentials or log raw signatures.
- Return downloads with validated content type and safe disposition. Never
  reflect untrusted filenames or headers into the response.
- Keep bytes, prompts, provider payloads, secrets, storage keys, and signed
  pulls out of logs and audit payloads.

## 10. Delivery, Acknowledgment, And Local Write Boundary

WordPress retrieves an available artifact with `SIGNED_PULL`. The direct HMAC
request is timestamp-bounded, bound to the authenticated site and artifact
path, and consumes a one-time nonce. Cloud does not mint a bearer URL, push
media bytes to an arbitrary callback URL, or treat a caller-provided URL as a
delivery target.

After download, WordPress must independently verify byte count, checksum,
magic bytes, MIME, and decode. It must then recheck local actor permission,
object revision, policy, approval, and preflight before presenting or applying
the result.

Only the local WordPress path may import into the media library, create or
replace an attachment, set a featured image, insert media into content, update
metadata, publish, or record the canonical local audit event. Cloud owns none
of those operations and never infers them from a successful runtime job.

`delivery-ack` is site-scoped and idempotent. WordPress may send it after a
verified transfer has completed. The acknowledgement records delivery evidence
without changing `expires_at`; it grants no write permission and carries no
claim that the artifact was reviewed or applied. This preserves the immutable
result descriptor for a later reviewed local adoption within the original TTL.

## 11. Retention, Purge, And Observability

Every source and result artifact has a short, explicit TTL. `expires_at` is
server-owned and bounded by operation and plan policy. An unavailable client or
missing acknowledgement never converts temporary storage into permanent
storage.

Cleanup requirements are:

- remove partial upload and processor-output files after validation, timeout,
  cancellation, worker failure, or store failure;
- purge expired bytes through idempotent `ArtifactStore.delete` and retain only
  the minimum tombstone or runtime evidence required by policy;
- reconcile metadata without bytes and bytes without metadata; C2a reports
  aggregate mismatch evidence after a bounded safety window but does not clean
  observed orphans;
- preserve the original server-owned `expires_at` after delivery
  acknowledgement; retention-before and retention-after evidence remain equal
  and ACK never becomes a retention mutation;
- retry failed deletion without restoring artifact availability;
- prevent expired or purged artifacts from receiving new signed pulls or ACKs;
- serialize ACK and purge decisions on the artifact row so acknowledgement
  cannot extend or revive an expired, purge-pending, or purged artifact.

P3-B4C1b implements the TTL-purge portion with database truth and a two-stage
lease:

- `storage_key` is globally unique. `purge_claim_id` and
  `purge_claim_expires_at` are either both present or both absent. Migration
  `0065` starts a real SQLite `BEGIN IMMEDIATE` transaction before checking for
  duplicate storage ownership, refuses duplicates before any DDL, and does not
  reveal the duplicate key or repair it automatically;
- cleanup fairly selects expired, retry-due candidates, then claims each with a
  full eligibility `UPDATE` compare-and-set. The claim transaction locks the
  artifact first and then all unacknowledged, unrevoked deliveries in ascending
  `delivery_id` order. Those deliveries are revoked before the claim commits.
  After revocation flushes, the transaction refreshes every matching claim
  lease from the actual logical clock immediately before commit, so time spent
  coordinating deliveries does not consume the delete worker's lease;
- the transaction closes before `ArtifactStore.delete`. Success or failure is
  finalized in a new short transaction fenced by artifact ID, claim ID,
  unpurged state, and `purge_pending`. An old lease cannot finalize over a newer
  claim. Retry time and `purged_at` are measured after delete returns;
- an expected `ArtifactStoreError` records only
  `artifact_store.delete_failed`, schedules a capped exponential retry, clears
  the lease, leaves deliveries revoked, and lets cadence succeed with counts.
  Any other ordinary delete exception first attempts the same fenced safe
  failure finalize, then raises only stable
  `media_artifact.lifecycle_cleanup_failed` semantics so cadence records an
  error without exposing exception text, keys, or paths. A `BaseException`
  crash after an idempotent delete leaves the active lease for stale reclaim.
  Ordinary candidate, claim-CAS, revocation, lease-refresh, and claim-commit
  database errors are wrapped at the lifecycle-service boundary with the same
  stable error and no SQL or parameters; `BaseException` still escapes;
- the cleanup cadence identity remains `artifact_cleanup` and emits exactly
  `claimed`, `purged`, `retry_scheduled`, `stale_claims_reclaimed`, and
  `superseded_finalizations`. IDs, storage keys, paths, and exception text are
  not cadence evidence.

The same artifact-first lock order applies to signed-pull preparation, stream
completion, ACK, and purge. Preparation takes its first production time
snapshot only after locking the artifact, then rechecks lifecycle, expiry, and
the 300-second window after store metadata/open and again after the first
delivery flush. The last valid pre-commit snapshot becomes `started_at` and the
ACK-deadline basis. A post-flush crossing best-effort closes the stream and
rolls back, so no delivery is committed. Immediately after commit and before a
response can expose bytes or headers, a short artifact-then-delivery locking
transaction takes a read-only lifecycle snapshot. Only after both the
preparation and revalidation sessions have completely exited does the runtime
take its final production time and require both the artifact expiry window and
delivery ACK window to retain more than 300 seconds. A crossed post-commit
boundary first closes the stream, then independently and best-effort deletes
only a pristine never-exposed delivery. Completed, acknowledged, or revoked
delivery evidence is never deleted. Compensation or session-exit failure
cannot replace an existing commit or admission error. Artifact purge/expiry is
evaluated before delivery terminal state, so purge still returns 410 even when
that delivery is already revoked. If the snapshot otherwise permits signing,
a `BaseException` from revalidation-session exit escapes unchanged and an
ordinary exit failure maps to stable 409. Crossing expiry returns 410; crossing
only a safety window returns public 409
`media_artifact.delivery_window_unavailable`. Explicit `now=` remains a frozen
deterministic test clock. A stream already issued may record completion after
wall-clock expiry, but not after purge has claimed the artifact, the delivery
has been revoked, or the locked delivery's expected byte size/checksum differs
from the completion facts. For a first ACK, any artifact status other than
`available` (including failed or unknown future states), or revoked,
deadline-expired, purged, or time-expired state, returns unified 410
`media_artifact.delivery_expired` before incomplete-delivery evaluation. An
exact committed ACK replay remains successful after purge and never changes
retention again; a conflicting replay remains 409.

The C1b migration and race-state proof is SQLite-based. It proves schema shape,
constraints, destructive downgrade shape, pre-DDL duplicate rejection, CAS
state transitions, lease recovery, and deterministic orderings in the focused
harness. The migration proof enables SQLite FK enforcement and retains a
near-full `media_artifact_deliveries -> media_artifacts` inbound FK, delivery
row, and delivery indexes through upgrade and downgrade. It exercises normal
Alembic SQLite per-migration connections whose DBAPI transaction is initially
inactive, starts the transaction before duplicate validation or DDL, restores
deferred-FK state after a clean `foreign_key_check`, and proves injected
upgrade/downgrade failures roll back without temporary tables or partial
schema loss and can be retried directly. Failure cleanup cannot mask the
original migration exception. A successful FK check is not commit-ready until
strict `PRAGMA defer_foreign_keys=OFF` succeeds; a `BaseException` from that
restore escapes unchanged, rolls back schema and version state, and permits a
direct retry. It is not a claim of PostgreSQL production concurrency behavior.
P3-B4C2a provides read-only inventory reconciliation. P3-B4C2b adds persistent
two-complete-pass candidate truth, per-candidate fixed-root fencing,
all-status final recheck, conditional unlink, retry, and crash convergence;
automatic cleanup remains configuration-disabled by default.
P3-B4C3 separately proves PostgreSQL major 16, migration head `20260716_0066`, distinct
simultaneously live connections, active-pass and candidate-claim contention,
stale-finalizer fencing, cross-container publication locking, and two complete
safety-window passes on one isolated project-owned named volume. This proof is
not production enablement. P3-B4D is complete: its real smoke verified the
exact npcink WordPress root/home/plugin sources, upload-to-job artifact chain,
signed-pull delivery and transfer-only ACK evidence, Core proposal/audit truth,
local byte/checksum/decode/metadata/reference proof, HTTP delivery and page
visibility, explicit restore, and fixture cleanup. This evidence does not
enable production cleanup.

Metrics and redacted diagnostics must cover upload/download byte counts and
duration, validation rejects, queue age, processing latency, success/failure,
checksum mismatch, signed-pull admission and use, delivery acknowledgements,
expiry and purge lag, orphan counts, deletion failures, and store capacity.

P3-B4B3 makes `MediaArtifactDelivery` the only delivery-lifecycle evidence for
the media observability summary. Summary v2 reports started, stream-completed,
and client-receipt-acknowledged counts for the UTC `started_at` cohort, with
completion/started and acknowledgement/completed rates. It joins
`MediaArtifact` by artifact and site for platform-neutral operation and site
breakdowns. Completion requires matching completed byte size/checksum;
acknowledgement additionally requires ordered timestamps, matching received
facts, and both verification flags. Completion and acknowledgement remain
transfer evidence, never CMS apply/write evidence.

Metrics may aggregate by site, operation, media kind, provider, and result
status subject to authorization. They must not expose artifact bytes, raw input,
provider URLs, storage keys, or signed pull credentials.

## 12. Keep / Change / Delete / Defer

- **Keep:** Keep the existing FastAPI runtime, provisioned site auth,
  HMAC/nonce/idempotency, workers, provider routing, run evidence, usage,
  entitlement, health, diagnostics, and local governance ownership.
- **Change:** Move media to one streamed artifact envelope, typed processors,
  `ArtifactStore`, signed pull, delivery acknowledgement, TTL, purge, and
  site-scoped observability.
- **Delete:** Database media blobs, request/result JSON or Base64 bytes, the
  legacy authenticated/public-token routes, and the permanent audio-asset
  playback surface are removed through P3-B4B2.
- **Defer:** Defer audio, video, document processors, resumable upload,
  S3-compatible storage, CDN/gallery behavior, permanent storage, and arbitrary
  media pipelines until measured need.

P3-B2 changed only transport for the former combined POST and its exact proxy
allowance. P3-B3A then performed the atomic replacement: the upload resource
retains that transport, the JSON job resource uses artifact references, the
former POST is gone, and active producers, consumers, projections, fixtures,
tests, and proxy paths use the new contracts. Canonical HMAC fields, CMS
ownership, and final local write truth remain unchanged. Signed pull/ack and
delivery evidence are implemented in B4B1; B4B2 removes the audio-specific and
legacy delivery routes without deleting the audio-generation business
capability.

## 13. WordPress Acceptance For P0-P5

- **P0:** This target contract is accepted with stable marker and link checks.
  No route or implementation is represented as complete.
- **P1:** The canonical site and connector envelope can carry site, trace,
  idempotency, storage posture, and object correlation without granting media
  write authority or keeping compatibility aliases.
- **P2:** The WordPress text loop remains suggestion-only and does not gain a
  media side door around local review, approval, audit, or final write truth.
- **P3-B1/B2:** Metadata-only `MediaArtifact`, local-volume `ArtifactStore`,
  bounded download, byte-first purge, and the former media derivative
  route's streamed signed ingress are implemented and covered by focused
  tests as historical foundations.
- **P3-B3A:** Two of four unified resources are implemented: streamed upload
  and artifact-referenced image job. Durable runtime inputs contain references
  and typed parameters only; the former combined POST and its Base64 queue
  fields are deleted.
- **P3-B3B1/B2:** Image-generation output and WordPress alt-text vision input
  converge on artifact references. Provider URL/data-URL transport is private,
  transient, and absent from public and durable contracts. Addon upload handoff
  and real WordPress evidence completed through P3-B4D and P3-B5.
- **P3-B4A/B4B1/B4B2/B4C1/B4C2a/B4C2b/B4C3:** Current lifecycle is projected
  at public media envelopes except `media_derivative_result.v1`, whose artifact
  remains the immutable exact 12-field WordPress descriptor. Signed pull and
  ACK enforce its live availability without adding `status` or `purged_at` to
  that descriptor. Signed pull, verified stream completion,
  independent delivery evidence, credential stripping, and strict transfer ACK
  are implemented.
  Legacy delivery routes and the permanent audio-asset playback surface are
  deleted. Transaction-tracked publication, fenced TTL purge/delivery
  coordination, fixed-root publication fencing, read-only two-direction
  inventory reconciliation, and persistent default-off two-pass orphan cleanup
  are implemented. The isolated PostgreSQL 16 multi-connection/named-volume
  proof is complete without enabling production cleanup.
- **P3-B4D:** Complete on 2026-07-16. The fail-closed smoke passed against the
  npcink local site and live development Cloud with artifact-only
  `media_derivative_result.v1`, Addon upload/job/signed-pull/ACK evidence, Core
  proposal/audit, exact local adopt/reference/HTTP/restore facts, and complete
  WordPress fixture cleanup. This is acceptance evidence, not production
  cleanup authorization.
- **P3-B5:** Complete on 2026-07-16. Exact plugin and Cloud packages, a fresh
  WordPress 7.0.1/PHP 8.2.29 E2E, bounded-memory/performance limits,
  cross-site/expiry/replay security, upgrade/rollback/store recovery, media
  alias removal, the six-repository central matrix, and independent review
  passed. Its durable evidence record is
  [Media Runtime B5 Closeout 2026-07-16](media-runtime-b5-closeout-2026-07-16.md).
  It does not enable production orphan cleanup and it is not the global P5
  milestone.
- **P3 target:** The four target resources, typed image contracts, security
  controls, signed pull, delivery acknowledgement, TTL, and purge are
  implemented and covered by focused tests.
- **P3:** A real WordPress smoke proves upload, processing, signed pull, local
  checksum/type/decode verification, review, governed media import, and local
  audit. Cross-site access and arbitrary callback delivery fail closed.
- **P4:** Portal and Admin may show bounded read-only media run, usage, expiry,
  purge, and diagnostic evidence. They expose no media library or apply control.
- **P5:** Bounded-memory streaming, security, cleanup, retry, isolation,
  cross-repository matrix, exact deploy-bundle smoke, and real WordPress
  end-to-end evidence close the milestone.

Acceptance always requires `LOCAL_MEDIA_WRITE`: Cloud does not import, replace,
assign, insert, or publish WordPress media. A successful run, signed pull, or
delivery acknowledgement is never proof of local application.

## 14. Future Media Extension Seam

Audio, video, or document support may be added later by introducing a new
`media_kind`, a versioned typed operation contract, and a bounded processor.
The new kind reuses the same runtime, site isolation, artifact envelope,
`ArtifactStore`, signed pull, acknowledgement, TTL, purge, and observability.

Each extension must define its own content validation, decoder safety, byte,
duration, page, frame or pixel limits, metadata policy, provider-fetch policy,
timeouts, and WordPress-local review/write handoff. It must not weaken the
image contract or turn the common envelope into an arbitrary parameter bag.

Future media types are not part of this implementation round. They must not
clone the runtime, queue, artifact store, delivery path, CMS adapter, or
control-plane truth.

## 15. Non-goals

- B4C2a does not automatically delete inventory observations, consume the
  Session-local quarantine, or infer sites/filesystem paths from opaque keys.
  Pre-GA operators must still explicitly reset dropped historical audio data
  and its old volume before the destructive migration can proceed.
- Introducing Kafka, Celery, Temporal, RabbitMQ, a second scheduler, or another
  workflow truth.
- Building a Cloud media library, gallery, DAM, CDN product, or permanent
  object-storage product.
- Allowing Cloud CMS writes, direct WordPress media import, attachment changes,
  featured-image assignment, content insertion, or publication.
- Designing a universal CMS media/content model or moving CMS permission and
  review semantics into Cloud.
- Building a universal media DAG, arbitrary instruction processor, user-defined
  pipeline, or general workflow engine.
- Using PostgreSQL, JSON, Base64, `run_records`, logs, or audit events as media
  byte storage.
- Pushing bytes to arbitrary callback URLs or accepting arbitrary remote media
  fetches.
- Implementing audio, video, or document processors in P0-P5 unless a later
  reviewed contract explicitly changes the phased plan.
- Treating an S3-compatible backend as a prerequisite for the first media
  runtime implementation.
