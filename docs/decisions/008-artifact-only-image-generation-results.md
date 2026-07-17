# ADR-008: Artifact-only image generation results

- Status: Accepted
- Date: 2026-07-15

## Context

The pre-GA image-generation contract allowed callers to select `url` or
`b64_json`. Provider URLs and Base64 could then enter generic provider output,
`run_records.result_json`, execute responses, callbacks, and WordPress-specific
post-processing. One branch even downloaded a provider URL only to encode the
same bytes into Base64. That design coupled the public runtime to provider wire
formats, amplified memory and database payloads, and exposed an under-specified
remote-fetch seam.

The stable image profile name does not identify the current upstream wire
contract. The exact routed model is `Tongyi-MAI/Z-Image-Turbo`, and the current
[SiliconFlow image API](https://api-docs.siliconflow.cn/docs/api/images-generations-post)
documents a generated URL with a one-hour lifetime. It does not document a
Base64 response option. Requiring Base64 or changing models merely to avoid a
download would therefore be an unsupported production assumption.

Cloud already has the required destination boundary: metadata-only
`MediaArtifact`, a local-volume `ArtifactStore`, same-site authenticated
download, TTL cleanup, provider-call evidence, and durable run truth. Cloud
does not need a second image runtime or a WordPress media-library role.

## Decision

Atomically redefine the active `image_generation_request.v1` and
`image_generation_result.v1` contracts without a compatibility version.

The public request:

- accepts bounded generation intent and context only;
- requires a string `prompt`, strictly types `n`, `aspect_ratio`, and
  `resolution` without coercion, and rejects the old `text` alias;
- rejects `response_format`, URL, Base64, data-URL, download, fetch, provider
  transport, secret, and CMS-write fields;
- does not let callers select a provider media transport; and
- rejects `storage_mode=no_store` because a generated image must become a
  short-lived artifact.

Provider adapters expose generated media through a typed, non-JSON
`ProviderMediaCandidate`. A candidate carries either strictly decoded bytes or
a provider URL, never both. Provider URL, Base64, raw response payload, and
backend storage keys are absent from generic provider output and never become
runtime result fields.

For image-generation HTTP failures, the adapter discards the entire upstream
error body and exposes only the mapped error code plus a canonical message.
This prevents an upstream echo of a prompt, signed URL, Base64 payload, or raw
request from reaching run storage, execute/result responses, callbacks, or
logs.

Provider connections may configure:

- exact `image_output_hosts` for URL-returning image providers; and
- an optional provider-wire `image_response_format` where that upstream
  actually supports it.

Missing or invalid host configuration fails closed. Returned hosts do not add
themselves to the allowlist.

Provider URL retrieval is a private adapter-to-artifact operation. It requires
HTTPS on port 443, no credentials or fragment, an exact configured host, and a
DNS result set containing only globally routable addresses. Cloud connects to
an already-approved IP while preserving the original Host header and TLS SNI,
does not use environment proxies, rejects every redirect, and enforces wall
time and actual streamed-byte limits. One real deadline covers DNS, connection,
response headers, and the complete stream; bounded worker admission prevents slow
platform DNS calls from creating unbounded threads. A result that loses the
deadline race is closed and discarded.

Application logging forces the `httpx` and `httpcore` dependency loggers to
`WARNING` or above. Their INFO/DEBUG request records include full URLs and must
not persist provider asset query signatures or tokens.

Every candidate is fully decoded, restricted to a single bounded raster frame,
checked against MIME, magic, dimensions, total pixels, and aggregate run byte
budgets, then re-encoded after EXIF orientation handling. Re-encoding removes
EXIF, GPS, ICC, and format metadata. The sanitized bytes become a
`MediaArtifact` with operation `image.generate.v1`, the current run and site,
verified checksum and dimensions, and a short positive TTL.

Multiple candidates are all-or-nothing. Ordinary materialization, database,
normalization, run-finalization, or transaction rollback errors remove objects
published by the failed transaction. A process crash or genuinely uncertain
database-commit outcome remains an explicit B4 orphan-reconciliation case.

The result contains artifact references and verified metadata only. Retrieval
uses the separate signed-pull and delivery-ACK contract in ADR-011; no download
URL or credential is embedded in the result. It is marked
`suggestion_only=true` and `requires_local_review=true`. Signed pull and
delivery acknowledgement are implemented by ADR-011; orphan reconciliation
remains B4 work. WordPress
continues to own download verification, preview, review, media import,
association, publication, and local audit.

## Consequences

- Provider wire formats cannot leak through execute, result polling, callback,
  database, or log contracts.
- URL-only upstreams remain usable without turning the public runtime into an
  arbitrary fetch service.
- A URL-returning provider is unavailable until its output hosts are explicitly
  configured and verified by an operator.
- Generated media shares the same artifact, expiry, isolation, and future
  delivery boundary as transformed media while retaining a distinct typed
  operation contract.
- The public result is platform-neutral. No WordPress write or approval field
  is needed to prove that Cloud remains suggestion-only.
- A real provider smoke must discover and approve the current provider asset
  host before production image generation can pass; documentation or a model
  profile name is not a substitute for that evidence.

## Alternatives Considered

### Force `b64_json` for every provider

Rejected. The current upstream documents URL output only. Forcing an
undocumented option would make the active image capability fail at runtime.

### Switch to a different image model or provider

Rejected for this batch. Transport cleanup does not justify an unreviewed
quality, price, routing, or provider change.

### Trust any HTTPS URL returned by the configured provider

Rejected. A trusted API response is not authority to fetch arbitrary hosts or
private network addresses, and DNS can change between validation and connect.

### Keep URL and Base64 result variants for compatibility

Rejected. The project has no external users, and two result shapes would keep
the old persistence, callback, and security surface alive.

### Push the generated image directly to WordPress

Rejected. Cloud is a hosted execution and temporary-artifact owner, not a CMS
write owner. Local WordPress governance remains the final-write boundary.

## Rollback

Revert the public contract, typed provider-media seam, secure fetcher,
materializer, runtime finalization, tests, boundary documents, and this ADR as
one batch. Do not restore a public URL/Base64 compatibility path. Artifacts
already committed remain governed by their TTL and normal cleanup. If rollback
occurs because provider asset hosts cannot be safely configured, disable image
generation until a reviewed provider or fetch policy exists rather than
reopening arbitrary remote fetch.
