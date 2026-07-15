# ADR-010: Project Current MediaArtifact Lifecycle At Public Result Boundaries

## Status

Accepted

## Date

2026-07-15

## Context

Runtime result JSON records artifact metadata at creation time. The underlying
`MediaArtifact` continues through expiry and purge, so replaying the durable
snapshot could incorrectly advertise an artifact as `available`. The same
snapshot is exposed through run-result reads, initial and idempotent execution
responses, and delayed terminal callbacks.

Cloud owns this temporary runtime lifecycle detail. WordPress continues to own
permission checks, review, import, writes, and canonical local audit.

## Decision

Project current lifecycle state immediately before each public result leaves
Cloud. The projector:

- deep-copies the creation-time snapshot and never persists the projection;
- recognizes root `artifact` only for exact
  `media_upload_artifact` / `media_upload_result.v1` or
  `media_derivative_artifact` / `media_derivative_result.v1` markers;
- recognizes root `artifacts[]` only for exact
  `image_generation_artifacts` / `image_generation_result.v1` markers;
- recognizes root `audios[*].artifact` plus `items[*].artifact` only for exact
  `audio_generation_candidates` / `audio_generation_result.v1` markers;
- performs one bounded query for at most 100 unique artifact IDs, constrained
  by `site_id`, `run_id`, and artifact ID;
- reports `purged` before `expired`, treats `purge_pending` as publicly
  `expired`, and otherwise exposes the current artifact status;
- fails missing, over-limit, cross-site, and cross-run references closed as
  `unavailable`; and
- removes storage and purge-internal fields from recognized artifact envelopes.

The projection runs before analysis-envelope processing and inside the current
database session for callbacks. B4A does not change download URLs or introduce
signed-pull or delivery-ack contracts.

## Alternatives Considered

### Rewrite durable run result JSON during cleanup

Rejected because it couples cleanup to every historical result shape, creates
extra writes, and erases the creation-time evidence.

### Recursively scan arbitrary result JSON

Rejected because unrelated payloads may contain `artifact`-named fields and a
recursive scan would create an unbounded, ambiguous public contract.

### Trust the artifact ID without run and site scope

Rejected because it could project lifecycle state across tenants or runs.

## Consequences

- Public result outlets now agree on current artifact availability.
- Durable run results remain immutable creation-time evidence.
- The projector adds at most one bounded query per result containing a known
  media envelope and no query for unrelated results.
- Signed pull, delivery acknowledgement, purge metrics, and orphan
  reconciliation remain B4B+ work.

## Rollback

Remove the three projection call sites and this projection module. No schema,
stored bytes, or durable result JSON requires rollback.

## Verification

- focused projector tests cover known envelopes, lifecycle precedence,
  site/run isolation, missing references, the ID cap, non-recursion, and
  snapshot immutability;
- service tests cover run-result, transient and idempotent execution responses,
  and callback payload projection; and
- repository contract/domain gates remain the integration guard.
