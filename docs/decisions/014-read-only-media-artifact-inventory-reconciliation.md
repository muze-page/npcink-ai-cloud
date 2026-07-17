# ADR-014: Read-only Media Artifact Inventory Reconciliation

## Status

Accepted — P3-B4C2a implemented. P3-B4C2b is subsequently implemented by
ADR-015 without changing this read-only inspection contract.

## Date

2026-07-15

## Context

Artifact bytes are published before the referencing `MediaArtifact` database
row commits. ADR-012 compensates definitive rollbacks and quarantines uncertain
commit outcomes in the owning Session, but that quarantine is intentionally
process-local and non-durable. Volume loss or manual intervention can also
leave an available database row whose object is absent.

Operators therefore need bounded evidence in both directions:

- objects present in the byte store but absent from database truth; and
- available database artifacts whose object is absent from the byte store.

A safety window alone is not authority to delete. A publication may still be
between atomic object publication and database commit, and a one-pass scan can
race that transition. C2a must make the mismatch observable without converting
Cloud into a media library or a CMS write owner.

## Decision

Add an optional, platform-neutral `ArtifactInventoryStore` seam alongside the
unchanged `ArtifactStore` interface. The local-volume backend implements stable
keyset pagination and existence checks. The generic cursor is an opaque
backend continuation token: a non-null value means more matching objects
remain, tokens may not repeat within a traversal, and each backend must prove
that a quiescent traversal neither repeats nor skips matching objects.
Concurrent creates or deletes may become visible in the current or next full
traversal; one pass is never deletion authority. Within each page, storage
keys are unique and strictly ascending, and every later page begins after the
prior page's final key. It enumerates only the exact two-level hex shard
layout, exact opaque object keys, regular files with one hard link, and
metadata available from `stat`. Directory traversal is pinned with same-device
directory descriptors and `O_NOFOLLOW`, including when a shard is replaced
during a scan. Temporary names, malformed or wrong-shard objects, symlinks,
hard links, non-regular files, and the fence file are excluded. Enumeration
does not open or hash object bytes, and a missing store root is an empty
inventory.

Add a read-only `MediaArtifactReconciliationService` that:

- scans the store in bounded pages, then checks each page against every
  `MediaArtifact` status so tombstones remain valid references;
- reports unreferenced objects inside the safety window as deferred and objects
  at or beyond the fixed cutoff as eligible evidence only;
- scans available database artifacts by bounded storage-key pages and checks
  whether each object exists;
- closes each database Session before the next filesystem enumeration or
  existence check;
- validates monotonic, unique inventory pages and normalizes ordinary failures
  to one stable, path-free error; and
- never deletes or quarantines an object, changes an artifact status, infers a
  site from a storage path, or emits opaque storage keys in cadence evidence.

The independent ops cadence records only aggregate conservation evidence:
store examined, referenced present, orphan observed/deferred/eligible,
available database rows examined, referenced missing, deletion disabled, and
publication-fence support. The interval, safety window, and page size are
bounded deployment settings. C2a does not acquire the exclusive deletion
fence because it performs no destructive operation.

Add an optional `ArtifactPublicationFenceStore` seam for the future destructive
phase. The local-volume implementation uses a private `0600` `flock` file.
Every active publisher acquires a shared lock before `put` and holds it through
the definitive commit or rollback cleanup outcome. Uncertain commits keep the
shared lock until recovery ends the outer transaction, then enter the existing
no-delete quarantine and release it. A future reconciler can attempt an
exclusive non-blocking guard; C2a exposes and tests this capability but does
not use it to delete.

## Why Automatic Deletion Is Deferred

P3-B4C2b must not promote `orphan_eligible` directly into deletion. Destructive
cleanup requires, at minimum:

1. the same unreferenced key observed across two complete, durable inventory
   passes separated by the safety window;
2. a persistent database claim or lease so workers and restarts share one
   cleanup truth;
3. an acquired exclusive publication fence before the final decision;
4. a final conditional database recheck immediately before delete; and
5. idempotent delete plus fenced finalize/retry evidence that cannot erase a
   newly committed reference.

Those requirements need persistent coordination design and real concurrency
proof. They are deliberately outside this schema-free read-only batch.

## Consequences

- Operators gain bounded orphan and missing-object evidence without an unsafe
  cleanup action.
- Inventory and publication fencing remain optional store capabilities, so the
  existing public artifact interface and current fakes do not gain mandatory
  methods.
- The local volume now has one private lock file; it is operational metadata,
  not an artifact and not a public identifier.
- Publication may hold a shared filesystem lock for the duration of its outer
  database transaction. Current producers use the unified helper, and tests
  prove shared locks coexist while blocking exclusive reconciliation locks.
- C2a assumes a stable, service-owned artifact-volume root. Before C2b can
  delete, its exclusive guard, root-generation check, final reference check,
  and fd-relative conditional unlink must cover one pinned root identity; the
  current ordinary `delete` path is not orphan-deletion authority.
- Each cadence performs a complete read-only traversal. Cursor-aware shard
  skipping keeps work approximately linear in the current inventory, while
  page bounds cap the per-page item working set and database `IN` query size.
  Loop detection retains one opaque token per page for that traversal, so its
  memory grows linearly with page count; persistent checkpoints remain a later
  scale/destructive-coordination decision.
- No model, migration, public API, Portal/Admin, WordPress, CMS write, S3/CDN,
  capacity, or automatic-orphan-deletion contract changes in C2a.

## Verification

- strict inventory layout, pagination, cutoff, exclusions, missing-root, and
  stable-error tests;
- two-direction reconciliation, all-status reference, available-object
  absence, conservation, no-delete, and no-Session-during-filesystem-I/O tests;
- cross-process shared/shared coexistence and shared/exclusive exclusion;
- real local-volume publication fence tests for commit, rollback deletion,
  uncertain-commit recovery, and delete `BaseException` escape;
- non-idempotent guard ownership tests proving one release and preservation of
  the original `BaseException`; and
- independent ops cadence/config/deployment contracts with redacted aggregate
  evidence.
