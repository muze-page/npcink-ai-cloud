# ADR-013: Fence Media Artifact Purge Against Delivery Completion And ACK

## Status

Accepted — P3-B4C1b implemented

## Date

2026-07-15

## Context

The retained media cleanup helper selected expired rows and called
`ArtifactStore.delete` while its database transaction and optional caller-owned
Session were still open. It had no durable lease or finalize fence. A slow or
crashed delete could hold locks, duplicate work without ownership evidence, or
let an old worker overwrite a newer decision.

Signed-pull preparation, stream completion, ACK, and purge also did not share a
single lock order. ACK locked a delivery before its artifact, while purge needed
to decide the artifact lifecycle and revoke every unacknowledged delivery. Near
expiry, a new pull could be issued with too little time left to complete and ACK.

## Decision

Use `MediaArtifact` as the database truth for TTL deletion ownership:

- `storage_key` has the named global unique constraint
  `uq_media_artifacts_storage_key`;
- nullable `purge_claim_id` and `purge_claim_expires_at` form a named all-or-none
  check pair and claim expiry has a named index;
- migration `0065` starts a real SQLite `BEGIN IMMEDIATE` transaction before
  querying for duplicate storage keys and before any DDL. Any duplicate causes
  one stable pre-GA reset error without revealing the key, repairing rows, or
  partially changing the schema.

`MediaArtifactLifecycleService` accepts only the database URL and an
`ArtifactStore`; callers cannot lend it a Session. Cleanup uses two short
database stages around byte deletion:

1. Fairly select expired, retry-due candidates. Claim each with an atomic
   `UPDATE` compare-and-set containing the complete eligibility predicate, so
   correctness does not depend on SQLite row locks. The claim sets a unique
   five-minute lease, increments attempt evidence, clears the prior retry/error,
   locks the artifact first, then locks unacknowledged and unrevoked deliveries
   by ascending `delivery_id`, and records their first revocation time. After
   revocation flushes, refresh every still-matching claim lease from the actual
   logical clock immediately before commit; claim-transaction work therefore
   cannot leave an already-expired lease at delete handoff.
2. Commit and close before idempotent `ArtifactStore.delete`. Open a new short
   transaction and finalize with an `UPDATE` fenced by artifact ID, claim ID,
   unpurged state, and `purge_pending`. Success records `purged`; an expected
   `ArtifactStoreError` records only `artifact_store.delete_failed`, schedules
   exponential retry from the actual finalize time, clears the claim pair, and
   returns normal cadence counts. Any other ordinary delete exception first
   attempts the same fenced failure finalize, then raises a stable lifecycle
   error without its exception text, storage key, or path so cadence records an
   error. Ordinary candidate, claim-CAS, revocation, lease-refresh, and
   claim-commit database failures are wrapped at the outer service boundary in
   the same stable error, with SQL and parameters suppressed. A `BaseException`
   escapes unchanged and may leave the active lease for stale reclaim. A
   superseded worker is a counted no-op.

All participating delivery paths use this lock order:

```text
MediaArtifact FOR UPDATE
  -> MediaArtifactDelivery FOR UPDATE ORDER BY delivery_id ASC
```

Preparation locks the artifact before taking its first production time
snapshot and lifecycle check. It rechecks lifecycle, expiry, and the pull window
after store metadata/open and after the first delivery flush. The last valid
pre-commit snapshot is the delivery `started_at` and ACK-deadline basis;
crossing after flush closes the stream and rolls the transaction back. After
commit but before returning the prepared stream, a short artifact-then-delivery
locking transaction captures a read-only lifecycle snapshot. The final
production clock is taken only after both preparation and revalidation sessions
have completely exited; artifact expiry and delivery ACK deadline must then
retain more than 300 seconds. A crossed boundary closes the stream first, then
independently and best-effort deletes only a pristine never-exposed delivery.
The original 409/410 or commit error survives compensation, close, and session
exit failures. Completed, acknowledged, or revoked evidence is never deleted,
and artifact purge/expiry is evaluated before delivery revocation. Only a
snapshot that otherwise permits signing propagates a revalidation-exit
`BaseException` unchanged or maps an ordinary exit failure to stable 409.
`now=` freezes checks for deterministic tests. Completion owns a new transaction,
locks artifact before delivery, and writes completion only when the locked
delivery's expected byte size and checksum equal the supplied completion facts.
Purge revokes every
unacknowledged delivery, including completed-but-unacknowledged delivery, while
preserving acknowledged delivery evidence and never rewriting a prior
`revoked_at`. Commit/flush cleanup catches `BaseException`, closes the stream on
a best-effort basis, and always rethrows the original transaction failure.

ACK may perform an unlocked delivery-scope lookup, but it then locks artifact
before the target delivery and rechecks ownership. An exact committed replay is
successful even after purge and cannot change retention again. Conflicting
replay is 409. For a first ACK, revoked/deadline-expired/artifact-expired,
purged, or any artifact status other than `available`, including failed and
unknown future states, returns unified 410 before incomplete-delivery
evaluation. Exact terminal replay remains the first decision.

An otherwise available artifact with 300 seconds or less remaining refuses a
new pull with 409 `media_artifact.delivery_window_unavailable`. If the initial
post-lock snapshot is already inside that window, rejection occurs before store
access. If store metadata/open or a delivery flush consumes the remaining
safety window, the post-open or post-flush recheck best-effort closes the stream
and rejects; post-flush rejection rolls back the tentative delivery. If commit
itself consumes the artifact or ACK safety window, the post-commit signing gate
removes the pristine tentative delivery before rejecting. These decisions
expose no remaining time, storage identity, path, or retry header. An
already-issued byte stream may still record valid
completion after wall-clock expiry; purge-pending, purged, or revoked state
blocks new completion.

The existing `artifact_cleanup` cadence calls the lifecycle service and emits
exactly five counts: `claimed`, `purged`, `retry_scheduled`,
`stale_claims_reclaimed`, and `superseded_finalizations`.

## Alternatives Considered

### Hold the transaction while deleting bytes

Rejected because store latency and failure would extend database lock time and
still would not fence a worker whose lease was superseded.

### Use only `SELECT FOR UPDATE SKIP LOCKED`

Rejected as the correctness mechanism because SQLite does not provide the same
row-lock behavior. The eligibility `UPDATE` compare-and-set is authoritative;
`SKIP LOCKED` remains an optimization whose PostgreSQL behavior is deferred to
the C3 validation batch.

### Delete first and claim later

Rejected because delivery revocation and ownership would not be committed when
the external side effect begins.

### Add Redis or advisory-lock ownership

Rejected because the relational artifact row is already the durable lifecycle
truth. A second lock truth would add failure modes without replacing the
database finalize fence.

## Consequences

- Slow byte deletion holds no database transaction.
- Active leases are skipped, stale leases are reclaimable, and a crash after an
  idempotent delete converges by deleting again.
- Completion, ACK, and purge have deterministic winner semantics and no inverse
  delivery-to-artifact lock path.
- Delete failure leaves the artifact unavailable and all unacknowledged
  deliveries revoked while exposing only a stable error code.
- Cadence and projection outputs contain no claim IDs, lease timestamps,
  storage keys, paths, artifact IDs, or exception text.
- SQLite tests prove the 0064-to-0065 schema transition/downgrade with FK
  enforcement enabled, a populated near-full inbound delivery FK and its
  indexes, clean `foreign_key_check`, restored FK PRAGMAs, constraints, a real
  pre-validation `BEGIN IMMEDIATE`, pre-DDL duplicate refusal, atomic injected
  failure rollback with no temporary tables or partial schema loss, direct
  retry, strict successful-path FK-PRAGMA restoration whose `BaseException`
  rolls schema/version state back unchanged, CAS state transitions,
  lease/fence recovery, and ordering behavior.
  They do not prove PostgreSQL production concurrency.

## Deferred

- P3-B4C2b persistent, fenced orphan deletion after the read-only bounded
  inventory reconciliation and safety-window evidence accepted by ADR-014;
- P3-B4C3 PostgreSQL real-concurrency tests and PostgreSQL 16 migration
  validation;
- P3-B4D WordPress local verification/import/audit evidence;
- S3/CDN backends, capacity reconciliation, new schedulers, and strict-readiness
  promotion.

## Verification

- model and `0065` migration tests cover named unique/check/index constraints,
  full old-field/FK/JSON/index preservation, symmetric downgrade, and duplicate
  pre-DDL failure;
- lifecycle tests cover committed claim visibility before delete, ordered
  revocation, commit-time lease refresh after simulated slow revocation,
  success, expected versus unexpected failure evidence, finalize-time backoff,
  active lease skip, stale reclaim, superseded success/failure finalize, crash
  recovery, fairness, retry cap, and exact slow-success finalize time;
- delivery tests cover the 300-second boundary, initial no-store rejection,
  post-open and post-flush no-delivery rejection, last-valid pre-commit time,
  post-commit artifact and ACK-window rejection, pristine compensation,
  final clocks after both session exits, close-before-compensation,
  purge-before-revocation priority, terminal-evidence preservation, normal
  admission, transaction and session-exit cleanup precedence,
  completion/purge orderings, locked expected-fact validation, acknowledged
  versus unacknowledged revocation, terminal completion states, ACK priority,
  exact replay after purge, conflict, cross-site hiding, and integrity rejection;
- cadence/projection tests cover exact five-count evidence, private claim
  stripping, and claim-stage SQL/parameter suppression; and
- static contracts prove the old cleanup implementation is absent and every
  locked delivery path follows artifact-first order.
