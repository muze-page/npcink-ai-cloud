# ADR-005: Cloud-managed local-volume ArtifactStore

- Status: Accepted
- Date: 2026-07-14

## Context

Media derivative artifacts and promoted AudioAssets stored binary payloads in
PostgreSQL. That coupled relational runtime truth to large byte transfer,
forced whole-row reads for downloads, and made expiry a database-blob cleanup
operation. P3-B1 needs one platform-neutral byte seam without adding a new
media API, CMS control plane, or heavy storage infrastructure.

The project is pre-GA, has no real users, and explicitly accepts a destructive
schema reset. API, runtime-worker, and ops-worker can currently share one
Cloud-managed Docker volume.

## Decision

Introduce an `ArtifactStore` interface with `put`, `open`, `delete`, and
`metadata`. Its first backend is a shared local volume. PostgreSQL stores only
opaque `storage_key`, size, checksum, content type, lifecycle status, and
correlation metadata.

Writes use bounded reads, a caller-supplied hard byte budget, SHA-256 and size
calculation during transfer, mode `0600`, fsync, and atomic rename. Keys are
server-generated, validated opaque identifiers; paths and keys are never
public API fields. Downloads and playback iterate fixed-size chunks. Delete is
idempotent. After atomic rename, the implementation fsyncs the containing
directory. If that durability confirmation fails, it removes the published
name and fsyncs again; failure to confirm rollback raises a specialized
`ArtifactStoreError` carrying the published object's metadata, so callers are
never told that publication definitely did not occur. Purge deletes bytes
before recording `purged`; a delete failure leaves an unavailable, retryable
`purge_pending` record. Retry state is metadata-only (`purge_attempt_count`, last and
next attempt timestamps, and a stable error code). Exponential backoff removes
failed objects from the immediately eligible set; ordering by effective
eligibility time lets both new and due retry work progress without changing
the artifact expiry contract or persisting raw exception messages.

AudioAsset promotion copies the temporary source into a new store object so
source TTL cleanup cannot delete the durable asset.

## Alternatives Considered

### Keep PostgreSQL blobs

Rejected. It preserves the coupling, expands database backup/WAL pressure, and
cannot provide the intended streaming storage boundary.

### Adopt S3 or MinIO now

Deferred. It adds credentials, lifecycle policy, network failure modes, and
operational infrastructure before current scale requires them. The interface
keeps this replacement possible without branching business services.

## Consequences

- API, runtime-worker, and ops-worker must mount the same volume and root.
- Database backups no longer contain artifact bytes; volume backup/monitoring
  becomes a separate operator responsibility.
- A database commit failure after atomic publication can leave an orphan; a
  future reconciliation batch may remove unreferenced keys.
- Local-volume loss makes metadata unavailable for download but does not move
  WordPress approval, writes, or audit truth into Cloud.

Reconsider S3-compatible storage when measured evidence reaches any of these
threshold categories: projected volume use exceeds the provisioned capacity or
backup window; API/workers must run on multiple hosts without a safe shared
filesystem; or the required durability/recovery objective exceeds the volume's
documented backup and restore capability. Exact numeric SLOs belong to the
deployment capacity plan, not this code-level ADR.

## Migration and Rollback

`20260714_0061` intentionally drops and recreates temporary media-artifact and
development AudioAsset storage shapes. It does not migrate old blob bytes.
Before execution anywhere with valuable data, inventory and back up both
tables. Downgrade restores the legacy schema shape only; it cannot restore
discarded rows or bytes. Code rollback therefore requires restoring the
pre-migration database backup as well as reverting this batch.

P3-B1 leaves multipart/Base64 ingress, unified media upload/jobs, signed pull
and delivery ack, additional media operations, and S3/MinIO to B2-B5.
