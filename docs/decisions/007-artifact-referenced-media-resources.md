# ADR-007: Artifact-referenced media resources

- Status: Accepted; legacy delivery note superseded by ADR-011/P3-B4B2
- Date: 2026-07-15

## Context

P3-B2 bounded and authenticated the former media-derivative multipart route,
but the public request still combined upload and processing. The route
materialized source and watermark files as complete Python byte strings, and
the queue contract encrypted those bytes as Base64 inside `run_records`.
Uploads, job admission, worker execution, and artifact lifecycle therefore did
not have independent resource identities.

The repository is pre-GA and has no compatibility obligation. WordPress is the
current delivery priority, while future CMS adapters must be able to use the
same hosted runtime without inheriting WordPress-specific contracts. Cloud
must remain a temporary runtime and artifact owner, not a CMS media library,
approval service, or write owner.

## Decision

Replace `POST /v1/runtime/media-derivatives` atomically, without an alias, with:

- `POST /v1/runtime/media/uploads`, using `media_upload_request.v1`; and
- `POST /v1/runtime/media/jobs`, using `media_job_request.v1` and the
  `image.transform.v1` operation.

Upload multipart accepts exactly one `request` field and one `file`. It keeps
the P3-B2 sealed signed-body capture and auth-before-parse ordering. The file
remains disk-spooled and is validated through a seekable stream for MIME/format
agreement, magic/decode, an 8,192-pixel per-axis ceiling, a
16,777,216-pixel/64 MiB RGBA decode budget, frame count, byte count, and
SHA-256. The route does not call `UploadFile.read()` or create a full upload
byte string. `ArtifactStore.put` receives the validated stream and must return
the same byte count and checksum or the operation fails closed.

An accepted upload creates one synchronous succeeded `RunRecord` and one
available `MediaArtifact` with operation `image.upload.v1`. The run is
zero-credit non-AI evidence: media entitlement is checked before the put, but
commercial acceptance/usage is not recorded for the upload itself. Replay
validates the request fingerprint, artifact row, expiry, byte-store metadata,
and checksum before returning the existing run. A same-key conflict does not
write an object. A concurrent unique-key loser deletes its object before
returning replay, and uncertain cleanup is reported as storage-unavailable.

Runtime diagnostics retain upload runs in operational totals and report them
as `non_ai_zero_credit_runs`. Provider-call and usage-meter coverage use the
separate `ai_evidence_required_runs` denominator, so a healthy upload neither
fabricates model evidence nor triggers a hosted-model coverage alert.

A media job contains source and optional watermark artifact IDs plus strict
typed parameters, batch context, and result TTL. Admission is same-site,
image-only, available, unpurged, and requires enough remaining input TTL to
cover the 300-second worker timeout plus a safety margin. Idempotent replay is
checked before queue-capacity and input-TTL admission. A new run stores only
the normalized request in `input_json` and encrypted execution input; neither
contains bytes, Base64, or an internal storage key.

The worker resolves every input by artifact ID and `run.site_id`, rechecks
status and expiry, then performs a bounded store read verified against the
database byte count and SHA-256. Source and watermark failures have distinct,
stable not-found, expired, and unavailable codes. The current Pillow processor
still accepts bounded byte strings; changing that private processor interface
is deferred. Transform outputs use operation `image.transform.v1`.

The exact 52 MiB proxy location moves to `/v1/runtime/media/uploads` only.
`/v1/runtime/media/jobs` is ordinary bounded JSON under the global `/v1/`
limit. At the time of this decision, the old authenticated and public-token
downloads remained for B4; ADR-011/P3-B4B2 subsequently replaced and deleted
them in favor of the unified signed pull and ACK.

## Consequences

- Relational and queue runtime inputs contain artifact references and typed
  parameters rather than media payloads.
- Upload and processing idempotency can be audited independently.
- Validation performs multiple bounded stream passes and local-volume storage
  I/O in exchange for fail-closed evidence and bounded application memory.
- Input artifacts may expire before a delayed worker despite admission; the
  worker recheck turns that race into a stable failed run.
- Provider-wire Base64 that is required by an external provider protocol is
  outside this decision. It must not be copied into the public media resource
  contract or durable run input.
- ADR-011 later implemented signed pull and delivery acknowledgement. Broader
  media kinds, remote stores, and CMS-local writes remain separate work.

## Alternatives Considered

### Keep one upload-and-process route with internal artifact conversion

Rejected. It keeps transport, resource identity, and queue execution coupled,
and makes reuse by future CMS adapters harder to reason about.

### Retain a compatibility alias or dual-read queue contract

Rejected. There are no production users, and compatibility would preserve the
Base64 path and double the security/test surface.

### Store upload bytes directly in run input or relational JSON

Rejected. Encryption does not turn a large Base64 payload into an appropriate
queue or database contract.

### Add S3/MinIO as part of the split

Deferred. The existing `ArtifactStore` boundary and local volume are enough to
prove the resource contract; backend expansion requires measured need.

## Rollback

Revert the two public resources, job/input contract, worker artifact lookup,
proxy exact location, projections, tests, boundary document, and this ADR as
one batch. No dual-read migration is maintained. Committed `MediaArtifact`
rows remain eligible for existing TTL cleanup. A delete with uncertain outcome
returns 503; byte-store objects without metadata require the B4 orphan
reconciliation or explicit operator cleanup and are not covered by TTL purge.
