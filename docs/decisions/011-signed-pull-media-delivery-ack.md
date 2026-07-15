# ADR-011: Use Signed Pull and Verified Delivery ACK for Media Artifacts

## Status

Accepted — B4B2 implemented

## Date

2026-07-15

## Context

Media upload, transformation, image generation, and audio generation now share
short-lived `MediaArtifact` storage. Earlier results still exposed relative
download URLs, and audio generation minted bearer tokens in query strings.
Those locators could be persisted, copied, logged, or replayed independently of
the request authorization that created them. The previous authenticated GET
also had no dedicated nonce, replay, rate, or completed-transfer evidence.

Cloud must safely return generated or transformed bytes while remaining a
hosted runtime rather than a CMS write plane. The active product is WordPress
first, but the seam must be reusable by future CMS connectors.

## Decision

Adopt a credential-free artifact-reference result and a two-step,
platform-neutral transfer contract:

1. a nonce-protected same-site HMAC GET streams the exact artifact and creates
   independent delivery evidence; and
2. a strict idempotent HMAC POST acknowledges the exact received byte count and
   checksum, then only shortens temporary retention.

`MediaArtifactDelivery` is distinct from `ReplayReceipt`. A delivery is marked
complete only after verified normal EOF; that delivery row is the
platform-neutral completion evidence rather than a derivative-specific metric.
The ACK projection exposes `acknowledgement_scope=verified_transfer_only`; it
does not claim a CMS write, review, import, or publication state.

The public auth seam gains an explicit `replay_policy="media_pull"`. Its nonce,
rate, replay, and rejection evidence uses independent `public_pull_*` scopes.
The method-default policy remains unchanged for ordinary GET and POST callers.

Known media result envelopes are projected through an allowlisted sanitizer so
historical URL, public-token, signed-query, and Base64 fields cannot leave Cloud.
The creation-time run snapshot is not rewritten.

The exact Nginx pull location is GET-only, disables response buffering, and
adds a 5r/s burst-10 per-IP rate zone plus 4 per-IP and 16 global connection
limits. Existing production runtime limits remain additive. Proxy access logs
omit query strings and referrers, and the pinned Compose proxy network uses the
same CIDR trusted by the API when resolving the client address.

## Alternatives Considered

### Keep relative or public-token URLs in result JSON

Rejected because a durable result would continue carrying a transport
credential or locator, and query tokens are especially likely to enter logs.

### Push artifacts from Cloud to each CMS

Rejected because it creates SSRF and credential-management risk, couples Cloud
to every CMS, and makes Cloud a second write/control plane.

### Reuse ReplayReceipt as delivery evidence

Rejected because request admission and verified byte transfer have different
lifecycle, integrity, retention, and audit semantics.

### Buffer the full response before returning it

Rejected because it increases memory and latency and does not prove that the
client received the bytes. Streaming completion plus client ACK supplies the
two distinct evidence points without full-body buffering.

## Consequences

- Result JSON and callbacks remain credential-free and platform-neutral.
- Replay, cross-site access, stale artifacts, byte mismatches, truncation, and
  ACK conflicts fail closed with deterministic status codes.
- Cloud can measure started, completed, and acknowledged transfers separately.
- ACK reduces exposure by shortening retention but cannot extend or delete it.
- ACK and purge serialize on artifact lifecycle state; acknowledgement cannot
  revive an expired, purge-pending, or purged artifact.
- Local connectors still verify, review, import, write, and audit under local
  CMS governance.
- B4B2 removes the legacy authenticated/public-token routes and helpers plus
  the permanent audio-asset promote/playback model, table, and configuration.
- Audio generation remains a hosted runtime capability and produces only a
  short-lived `MediaArtifact`; WordPress retains local verification, review,
  import, write, and audit ownership.
- The destructive `0063` migration refuses to drop a non-empty legacy table.
  A pre-GA operator must explicitly clear old rows and reset their copied-byte
  volume first; downgrade restores an empty shape, not deleted data.
- The retained derivative download-count projection is non-canonical and
  awaits B4B3 convergence on `MediaArtifactDelivery`.

## Rollback

Pause connector rollout of the pull/ACK consumer contract and revert the
application change if the contract itself is defective. Downgrading `0063`
recreates only an empty legacy table and does not restore deleted rows or
bytes; restoring the permanent playback surface is not an automatic rollback.
Do not restore URL/Base64/token fields to public results. Existing artifact TTL
cleanup remains the safe fallback while a corrected delivery contract is
prepared.

## Verification

- happy-path pull, completion, ACK, exact replay, and retention shortening;
- nonce/replay scope isolation, cross-site 404, query/idempotency/Range rejection;
- unavailable, expired, storage-mismatch, interrupted, checksum-mismatch, and
  oversized stream behavior;
- strict ACK validation and conflict behavior;
- producer and lifecycle-projection credential stripping;
- `0063` non-empty fail-closed, empty-table upgrade, and shape-only downgrade;
- static absence of legacy routes, token helpers, permanent audio-asset model,
  and dead derivative download writer; and
- exact Nginx route, rate, connection, GET-only, and no-buffering contract tests.
