# ADR-009: Artifact-referenced alt-text vision input

- Status: Accepted
- Date: 2026-07-15

## Context

The pre-GA WordPress `alt_text_suggest` operation accepted an HTTP(S) URL or
an image data URL directly in its scene request. That made provider transport a
public connector concern. Remote URLs could carry short-lived credentials or
delegate an under-specified fetch to the provider, while data URLs duplicated
media bytes in request handling and could reach generic object representations.
Caller-supplied MIME also competed with the actual stored media type.

Cloud now has a streamed, authenticated media-upload resource, a site-scoped
metadata-only `MediaArtifact`, a local-volume `ArtifactStore`, integrity-checked
reads, expiry, and purge. Image jobs and image generation already use artifacts
as the durable media boundary. Alt-text vision should use the same boundary,
without adding a second runtime or granting Cloud any WordPress write role.

The project is pre-GA and has no compatibility requirement. Preserving both
URL/data-URL and artifact forms would keep two security and persistence models
alive for no product benefit.

## Decision

Atomically replace the visual source in the active
`wordpress_operation.v1/alt_text_suggest` contract with one required
`source_artifact_id`. There is no compatibility alias or dual-shape request.

The public scene request accepts only the canonical fields
`source_artifact_id`, `prompt`, `filename`, `title`, `existing_alt`,
`existing_caption`, `locale`, and `max_tokens`. It rejects unknown, aliased,
case-variant, whitespace-variant, and duplicate field names instead of
normalizing them. `prompt` is a required nonempty string of at most 500
characters; optional context values are bounded strings; and `max_tokens` is
an optional non-Boolean integer from 1 through 96. Container or coercible
scalar substitutes fail before run creation. The contract also recursively rejects
`image_url`, `thumbnail_url`, caller MIME, data URL, raw Base64, storage key,
provider transport, credential, and WordPress-write values. The
operation's default data classification is `internal`, because a locally
selected WordPress image is not necessarily public.

Cloud admits the reference only when it resolves to an artifact belonging to
the authenticated site and the artifact is an available, unpurged, unexpired,
bounded JPEG, PNG, or WebP image. Cross-site and unknown identifiers are
indistinguishable. Resolve and new execute admission inspect metadata only;
they do not read media bytes.

Idempotent execute replay is checked before current source admission. A
previously completed run therefore remains replayable after its input artifact
expires. This does not authorize a new provider execution with an expired
source.

Immediately before a real provider execution, including queued worker
execution, Cloud revalidates the artifact and performs one bounded store read
with expected byte size and checksum. Missing or corrupt storage fails closed.
The verified bytes and content type are held in a non-serializable,
representation-safe value. Only the provider preparation edge creates a
transient data URL for provider compatibility.

The transient bytes and data URL must not enter `run_records.input_json`,
encrypted execution input, result JSON, callback payload, error evidence, or
logs. Provider request representations omit input payloads. Vision upstream
HTTP errors are reduced to the mapped taxonomy code and a canonical message at
both the adapter and runtime persistence boundaries, so an upstream echo cannot
reintroduce image bytes or prompt context.

The normalized operation result is a strict text-only projection containing
only bounded `output_text`. Raw provider fields and nested successful-response
echoes are discarded. If the selected output text itself contains an inline
media transport, normalization fails closed rather than persisting it. The
outer `cloud_connector_result.v1` remains `suggestion_only=true`. WordPress owns
attachment selection, permission checks, upload orchestration, review,
approval, metadata write, and local audit.

## Consequences

- Alt-text vision shares one site isolation, expiry, checksum, and byte-store
  boundary with the rest of the media runtime.
- Public connector requests and durable runs contain references and bounded
  text context, never media bytes or provider-fetch URLs.
- Provider compatibility remains private and replaceable; another vision
  provider can consume verified bytes without changing the public contract.
- The addon must upload the local attachment and pass the resulting artifact
  ID before advertising the complete capability. That handoff is a separate
  WordPress batch.
- An image accepted by general media ingress may still be too large for the
  stricter 8 MiB vision-input budget; callers must fail visibly and may create a
  bounded derivative before a later retry.
- Signed result pull, delivery acknowledgement, dynamic lifecycle projection,
  and orphan reconciliation remain P3-B4 work.

## Alternatives Considered

### Keep public HTTP(S) URLs

Rejected. URL reachability, credentials, expiry, redirects, and provider-side
fetch behavior would remain outside the artifact integrity and site-isolation
boundary.

### Keep bounded data URLs

Rejected. A byte cap does not prevent media duplication across request,
debugging, and serialization surfaces, and it retains a second ingress path.

### Let the vision provider read Cloud's download URL

Rejected. It would require exposing a delivery credential to the provider and
would couple execution to the later signed-pull contract. Cloud already has the
bytes and can translate them privately at the provider edge.

### Copy WordPress attachment metadata into Cloud truth

Rejected. Filename, title, caption, and existing alt text are bounded request
context only. WordPress remains the attachment and final-write authority.

## Rollback

Revert the connector contract, artifact input loader, runtime integration,
provider privacy guard, tests, active boundary documents, and this ADR as one
batch. Do not restore a mixed URL/data-URL compatibility path. If artifact
handoff cannot be made reliable, disable alt-text vision until the upload path
is corrected rather than bypassing the media boundary.
