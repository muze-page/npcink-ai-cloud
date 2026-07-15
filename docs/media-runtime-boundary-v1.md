# Media Runtime Boundary v1

Status: P3-B3A upload and image-job resources implemented; B3B-B5 remain target work.

## 1. Purpose

Define the WordPress-first Media Runtime boundary for temporary, streamed,
site-scoped media processing in Npcink AI Cloud.

Cloud may ingest bytes, run a typed hosted media operation, retain a temporary
artifact, and expose a signed pull. WordPress remains the owner of local
permissions, verification, review, approval, media-library writes, object
assignment, publication, and local audit.

This document began as the P0 target contract. Section 3 records the implemented
P3-B1 byte-store foundation, P3-B2 streamed ingress, and P3-B3A upload/image-job
resource split. Signed pull/ack, broader provider-output convergence, and the
remaining lifecycle described for B3B-B5 are still target work.

## 2. Stable Markers

- `TEMPORARY_MEDIA_RUNTIME`: Cloud artifacts are temporary runtime outputs, not
  a media library.
- `STREAMED_MEDIA_BYTES`: uploads, provider fetches, and downloads use bounded
  streaming rather than whole-object buffering.
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

The current refactor plan identifies remaining media debt: source/provider byte
transfer still needs streaming, and the existing operation-specific paths still
need to converge on one media lifecycle. Historical database blob paths, current
request/result Base64 media payloads, and an audio-specific download-token
special case are migration inputs, not contracts to preserve.

The target state is one `TEMPORARY_MEDIA_RUNTIME` that serves typed operations
through the existing Cloud runtime foundation. It uses one metadata envelope,
one pluggable byte store, one site-isolated delivery model, and no second
runtime or WordPress control plane.

P3-B1 provides the metadata-only `MediaArtifact`, a local-volume
`ArtifactStore`, bounded artifact downloads, independent AudioAsset objects,
and byte-first purge. It deliberately preserves the existing artifact routes.

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
  unchanged. In the production Caddy-to-Nginx chain, Caddy sets `X-Real-IP`
  from `remote_host`; Nginx accepts it only from loopback/RFC1918 proxies so
  `$binary_remote_addr` continues to represent the real client for the
  per-client zones. Direct-client development/domain configs do not rewrite it.

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
- the former POST route has no compatibility alias. The existing authenticated
  artifact download and audio public-download remain unchanged and are not
  evidence of the future signed-pull contract.

P3-B3A still uses two disk I/O passes at ingress and may materialize one bounded
source plus watermark inside the Pillow worker because the current processor
accepts `bytes`. Provider-edge Base64 required by external provider protocols,
signed pull/ack, and broader media kinds remain B3B-B5 work.

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
6. **Signed pull:** WordPress receives a short-lived, one-time or limited-use,
   site-bound download authorization and streams the artifact from Cloud.
7. **Local verify/review/write:** WordPress verifies the bytes and checksum,
   rechecks permissions and local object state, presents review, and performs
   any approved local media write.
8. **Delivery ack/purge:** WordPress may acknowledge completed transfer. The
   acknowledgement may shorten retention before idempotent purge.

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
  - **target, not implemented**; verifies a signed pull and streams the matching
    site-scoped artifact;
- `POST /v1/runtime/media/artifacts/{artifact_id}/delivery-ack`
  - **target, not implemented**; records delivery completion only and may
    shorten the artifact TTL.

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
- Issue signed pulls with short expiry, site and artifact binding, and one-time
  or bounded-use semantics. Do not log raw signatures or signed URLs.
- Return downloads with validated content type and safe disposition. Never
  reflect untrusted filenames or headers into the response.
- Keep bytes, prompts, provider payloads, secrets, storage keys, and signed
  pulls out of logs and audit payloads.

## 10. Delivery, Acknowledgment, And Local Write Boundary

WordPress retrieves an available artifact with `SIGNED_PULL`. The pull is
short-lived, one-time or limited-use, and bound to the authenticated site and
artifact. Cloud does not push media bytes to an arbitrary callback URL and does
not treat a caller-provided URL as a delivery target.

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
and may shorten `expires_at`; it grants no write permission and carries no
claim that the artifact was reviewed or applied.

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
- reconcile metadata without bytes and bytes without metadata, then clean
  site-scoped orphans after a bounded safety window;
- shorten the remaining TTL after delivery acknowledgement while preserving a
  small retry grace period;
- retry failed deletion without restoring artifact availability;
- prevent expired or purged artifacts from receiving new signed pulls.

Metrics and redacted diagnostics must cover upload/download byte counts and
duration, validation rejects, queue age, processing latency, success/failure,
checksum mismatch, signed-pull issuance and use, delivery acknowledgements,
expiry and purge lag, orphan counts, deletion failures, and store capacity.

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
- **Delete:** Remove database media blobs, request/result JSON or Base64 bytes,
  and the audio-specific download-token special case when the implementation
  switches atomically.
- **Defer:** Defer audio, video, document processors, resumable upload,
  S3-compatible storage, CDN/gallery behavior, permanent storage, and arbitrary
  media pipelines until measured need.

P3-B2 changed only transport for the former combined POST and its exact proxy
allowance. P3-B3A then performed the atomic replacement: the upload resource
retains that transport, the JSON job resource uses artifact references, the
former POST is gone, and active producers, consumers, projections, fixtures,
tests, and proxy paths use the new contracts. Canonical HMAC fields, CMS
ownership, and final local write truth remain unchanged. Signed pull/ack and
the audio-specific delivery special case remain B3B/B4 work.

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
  fields are deleted. Signed pull/ack and remaining transfer convergence are
  not represented as complete.
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

- P3-B2 did not implement the four target unified routes, new schema,
  processors, or migrations; P3-B3A implements only upload and image-job
  resources.
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
