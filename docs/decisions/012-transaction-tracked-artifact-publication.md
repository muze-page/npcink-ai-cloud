# ADR-012: Track Artifact Publication Against the Owning DB Transaction

## Status

Accepted — P3-B4C1a implemented

## Date

2026-07-15

## Context

Media upload, derivative output, audio generation, and image generation publish
object bytes before their `MediaArtifact` rows can commit. Producer-local
`put/delete` compensation was inconsistent, and a failed database commit could
leave either an ordinary orphan or an unsafe cleanup decision.

The hardest case is a DBAPI commit call whose acknowledgement is lost. The
database may have committed even though SQLAlchemy raised. Deleting the object
after the caller performs a recovery rollback could then break a valid
`MediaArtifact` row.

## Decision

Use one platform-neutral `publish_and_track_artifact` helper for all four
active producers. It validates and joins the existing outer SQLAlchemy Session
transaction before calling `ArtifactStore.put`, then immediately tracks the
opaque storage key. A store-level publication-uncertain error is tracked from
its returned storage metadata before the original error is re-raised.
Tracking identity and all forget/quarantine transitions use the exact
`(ArtifactStore instance identity, opaque storage key)` pair, so equal keys
returned by different stores cannot merge their cleanup outcomes.

The Session tracker distinguishes:

- `commit_requested`: Session commit began, but the connection has not entered
  DBAPI commit;
- `commit_started`: the connection entered DBAPI commit and the outcome can no
  longer be proven from an exception alone;
- `committed`: the transaction completed successfully; and
- `rolled_back`: rollback is definitive before DBAPI commit began.

Ordinary rollback deletes active publications. Successful commit forgets them.
If commit started but no definitive outcome arrives, active publications move
to a deduplicated Session-local no-delete quarantine before later transaction
work can clean them. Recovery rollback and subsequent transactions never
delete that quarantine. A rollback-cleanup delete failure follows the same
rule: successfully deleted keys leave active tracking, while failed keys enter
the quarantine before the cleanup-uncertain error is raised.

Image-generation batches retain their explicit inner-batch cleanup and forget
successfully deleted keys, while quarantining failed deletes, so their
all-or-nothing domain behavior remains unchanged. The generic tracker resolves
only the outer transaction. Image generation is currently the only active
producer that owns a nested savepoint, and it retains this explicit cleanup;
generic nested-savepoint tracking is deferred beyond this batch. Other producers
rely on the Session tracker rather than duplicating manual rollback deletion.

## Alternatives Considered

### Delete every object when `Session.commit()` raises

Rejected because the database may already contain the referencing row when
the commit acknowledgement is lost.

### Treat every commit exception as uncertain

Rejected because flush-time integrity failures happen before DBAPI commit and
must remain definitive rollback cases, including upload idempotency races.

### Keep producer-specific compensation

Rejected because it leaves different media types with different tracking,
error, and transaction semantics.

## Consequences

- Publication compensation is consistent across upload, derivative, audio, and
  image-generation producers.
- The generic cleanup-uncertain error exposes opaque storage keys, never local
  volume paths. Callers may retain a domain-specific cleanup error factory.
- A commit-confirmation loss intentionally favors preserving possibly
  referenced bytes over unsafe deletion.
- The quarantine tuple lives only in `Session.info` for the Session lifecycle.
  It is an in-memory no-delete guard, not persistent or durable reconciliation
  evidence, and no production consumer reads it.
- Critical logs retain only an affected-artifact count; storage keys and local
  paths remain absent.
- ADR-014/P3-B4C2a discovers possible orphans through a bounded artifact-store
  inventory versus database inventory scan after a safety window. It does not
  depend on the Session-local quarantine tuple and performs no deletion.
- Automatic deletion of quarantined or unreferenced publications remains
  deferred to P3-B4C2b persistent coordination.
- No schema, migration, media-delivery, WordPress, or CMS-write contract changes.

## Verification

- success commit preserves the object;
- ordinary rollback and pre-DBAPI flush failure delete the object;
- store publication uncertainty is tracked and cleaned on definitive rollback;
- commit-confirmation loss moves publications out of active cleanup, survives
  recovery rollback and Session reuse, and deduplicates quarantine entries;
- rollback-cleanup delete failure moves only failed keys into quarantine before
  raising, and later same-Session commits do not forget them;
- connection-listener state is removed after success, flush failure, and
  commit-confirmation loss;
- image cleanup-delete failure, including first-only and persistent failures,
  leaves no `MediaArtifact` row and remains quarantined after a failed-run
  commit, while successful cleanup never enters quarantine;
- image nested-savepoint success followed by outer rollback still cleans;
- the active-producer AST contract proves image generation is the only current
  nested-savepoint producer and retains explicit cleanup; and
- active producer AST characterization denies direct `ArtifactStore.put` calls.
