# ADR-015: Persistent Fenced Media Artifact Orphan Cleanup

## Status

Accepted — P3-B4C2b implemented and P3-B4C3 isolated PostgreSQL 16,
multi-connection, and named-volume proof implemented. Runtime and deployment
configuration default cleanup to disabled. This decision does not record a
deployment action.

## Date

2026-07-16

## Context

ADR-014 deliberately made one inventory pass read-only. An old unreferenced
object is evidence, not deletion authority: publication occurs before the
referencing database commit, workers can crash between pages or after unlink,
and a configured local-volume path can be replaced while a process still has
the old root open.

C2b must recover ordinary orphans without converting Cloud into a CMS media
library, weakening the all-status `MediaArtifact` reference rule, or holding a
database transaction across filesystem I/O.

## Decision

Add durable reconciliation-pass and orphan-candidate state. Exactly one
`running` pass owns the active slot and exactly one completed pass may own the
head slot. Every page update is fenced by pass ID, active slot, claim ID,
unexpired lease, expected cursor, and expected last key. An expired incomplete
pass is abandoned and never resumed or promoted; a replacement always receives
a new pass ID. Only a fully scanned pass may atomically replace the completed
head.

The existing ADR-014 aggregate meanings remain unchanged:

- `orphan_observed = orphan_deferred + orphan_eligible`;
- `orphan_eligible` means only that the object passed the mtime age gate; and
- `cleanup_candidates_eligible` separately counts candidates promoted by the
  destructive two-complete-pass rule.

A cleanup candidate requires the same opaque key, store generation, and object
version in consecutive complete passes, with the second pass starting at least
the configured safety window after the first pass actually completed. Recent
or future-mtime objects do not create or extend continuity. A missed pass,
generation change, directory identity change, file identity/stat change, or
reference in any current or future `MediaArtifact.status` resets or invalidates
the candidate.

The local-volume backend adds fixed-root sessions:

- first publication into an existing empty root serializes generation-marker
  initialization with an independent private `.artifact-store-bootstrap.lock`;
  it publishes a private single-link marker by temp-file fsync, fd-relative
  replace, and root-directory fsync, then releases the bootstrap mutex before
  the publication session can cross a database transaction;
- read-only inventory treats a markerless existing root as empty only when no
  storage shard exists and creates no marker or lock; a markerless root with a
  shard fails closed;
- publication pins the root, private lock inode, generation marker inode, and
  store generation under a shared lock; it validates again immediately before
  database commit and rolls back through the pinned root;
- cleanup attempts one non-blocking exclusive session per candidate, then
  claims/reclaims that candidate, validates immediately before the final
  all-status database check, validates again before unlink, and performs an
  fd-relative conditional delete;
- object versions bind the generation, root and two shard `dev/ino` pairs, and
  the file's complete identity/stat tuple. Unrelated sibling churn does not
  invalidate a token;
- root, lock, marker, shard, and file replacement; symlink, hard-link,
  non-regular layout; unsafe owner/write permissions; or token drift fails
  closed; and
- an absent object is durable success only after fsync of the deepest existing
  pinned directory (leaf, first shard, or root) and repeated session
  validation.

Filesystem work never runs inside the claim/finalize transaction. Delete
success and durable absence finalize with a claim-token compare-and-set.
Ordinary failures schedule bounded exponential retry with a stable error code.
`BaseException` escapes unchanged and leaves the lease for stale reclaim. An
old worker cannot finalize over a newer claim. If unlink succeeds but finalize
is lost, the next stale claim converges through the durable-absence path.

Cleanup reuses the existing `artifact_inventory_reconciliation` ops cadence and
task count. It emits aggregate counts only—never storage keys, object versions,
generation values, claims, paths, SQL, or exception text. Deployment settings
are wired only to `ops-worker`; `artifact_orphan_cleanup_enabled` defaults to
false. The core five-method `ArtifactStore` surface remains unchanged, and the
fixed-root/inventory capabilities stay optional seams.

## Consequences

- Publication rollback and orphan deletion cannot be redirected from a pinned
  root A to a replacement root B.
- Deletion is conservative across restarts, concurrent workers, future status
  values, clock-safe pass completion, and unlink/finalize crash windows.
- The exclusive fence is held for one candidate only, not a whole scan or
  batch, limiting publication blocking.
- Pass completion promotes eligible candidates with one set-based correlated
  update over rows observed by the current pass; it does not lock or load
  historical candidate rows into application memory.
- Portal, Admin, public API, WordPress, CMS write ownership, media delivery,
  TTL purge, S3/CDN, and new scheduler contracts do not change.
- PostgreSQL real-concurrency, migration-head, and named-volume behavior are
  covered by the dedicated P3-B4C3 isolation proof. That proof is evidence for
  the enablement checklist; it is not a production enablement action.

## Threat Model And Enablement Boundary

The local fence is POSIX advisory locking, not a mandatory filesystem
capability. POSIX also provides no atomic "unlink only if this inode still
matches" primitive. The proof therefore depends on all of the following:

- the service account owns the root, shard directories, fence file, bootstrap
  lock, generation marker, and deletable object, while group/other write access
  is disabled;
- every namespace writer follows the shared/exclusive fence contract;
- operators do not replace the mount, configured root, shard directories,
  generation marker, or fence inode while the service is running; and
- no malicious or compromised process with the same UID bypasses the fence.

Identity, permission, repeated-stat, and fd-relative checks fail closed against
accidental drift and ordinary races within that cooperative model. They do not
claim protection against a hostile same-UID namespace writer deliberately
racing the final stat and unlink.

The ordinary focused suite continues to use SQLite state/CAS behavior and local
POSIX `flock`. P3-B4C3 adds a separate, explicit proof using PostgreSQL 16, two
simultaneously live app-container connections, and one Compose-project-owned
named volume. It proves active-pass exclusion; eligible, retry, and stale-claim
CAS; stale-finalizer fencing; cross-container shared/exclusive publication
locking; and two complete safety-window passes with default-isolated deletion.
Passing this proof does not enable production cleanup. Production automatic
deletion remains disabled until an operator separately completes every item in
the operations enablement checklist.

## Verification

Run the isolated proof explicitly; ordinary `check:fast` does not start it:

```bash
pnpm run check:artifact-orphan-isolation-proof
```

The gate creates a fresh random Compose project, starts PostgreSQL 16 plus two
app containers, mounts one project-owned named volume at
`/var/lib/npcink-ai-cloud/artifacts`, emits a bounded `PASS`/`FAIL` summary
containing only a fixed phase and numeric Compose exit code (never keys, paths,
tokens, claim identifiers, SQL, or exception text), and tears down only that
project's containers and volumes.

- migration upgrade/downgrade shape and named constraint proof;
- two-pass, age-gate, missed-pass, generation, token, cursor, lease, stale
  worker, CAS, retry, crash-recovery, and all-status reference tests;
- fixed-root publication validation at put, before commit, and after definitive
  commit before release;
- concurrent first-open, short bootstrap-mutex release, initializer-crash,
  atomic marker publication failure/retry, and markerless empty-root tests;
- cross-process shared/exclusive exclusion and per-candidate EX acquisition;
- root/lock/marker/shard/file identity, permission, link, non-regular, inode
  swap, sibling-churn, and deepest-directory fsync tests;
- stable ordinary errors, exact `BaseException`, and exactly-once/idempotent
  release tests; and
- unchanged ADR-014 read-only inspection, active-producer, nested rollback,
  ten-task cadence, default-off, ops-only deployment, and redacted aggregate
  evidence contracts.
