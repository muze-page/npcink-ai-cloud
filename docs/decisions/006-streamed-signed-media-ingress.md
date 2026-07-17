# ADR-006: Streamed signed media ingress

- Status: Accepted
- Date: 2026-07-14

## Context

`POST /v1/runtime/media-derivatives` authenticated an HMAC request by calling
`request.body()`, then read the cached body again and passed the complete bytes
to a one-shot `python-multipart` parser. A request near the media limit could
therefore occupy a large application-memory buffer before file limits or
multipart structure were known. The direct parser also did not provide an
explicit incomplete-message proof, bounded per-part header accumulation, or a
single cleanup owner for raw and file-part temporary resources.

The public HMAC canonical request, existing route, media derivative service,
artifact lifecycle, and WordPress-local write boundary must remain unchanged.
Authentication must still precede multipart syntax errors so an unauthenticated
caller cannot use parser behavior as an oracle. The project remains pre-GA,
but this transport seam should support larger media and future media kinds
without introducing a second runtime or CMS control plane.

## Decision

Add a frozen `PrehashedRequestBody` evidence type and an asynchronous evidence
loader seam to public request authorization. Existing callers continue to use
`request.body()`. The media derivative route is the only caller in this batch
that supplies the loader.

The loader owns a `SealedRequestBodyCapture`. Before it may receive the body,
authorization validates required auth headers, nonce, idempotency key,
signature syntax, and timestamp freshness, then opens one short-lived database
session to verify the active site, active key, and required scope. That session
is closed before body reception begins. The loader then:

1. validates an ASCII, bounded `Content-Length` as an early hint;
2. streams network chunks into `TemporaryFile("w+b")` while enforcing the
   configured actual-byte hard limit;
3. checks every write for full completion and computes SHA-256 over the same
   chunks;
4. seals the capture and returns its digest and byte count to authorization.

Authorization validates byte size before digest syntax and uses the supplied
digest in the unchanged canonical HMAC request. Only after successful
authorization may parsing replay the sealed capture. No code path may call
`request.body()` or `request.stream()` again after the capture is sealed.
After capture, authorization uses a new current time and a new database session
to revalidate timestamp freshness, site, key, and scope before resolving the
secret, comparing HMAC, and reserving replay evidence. This final check closes
the upload-time TOCTOU window without holding a database connection while a
large body arrives. Non-media callers keep their existing single final database
session, while receiving the cheap timestamp precheck.

Multipart replay uses a bounded wrapper around Starlette `MultiPartParser`.
It requires the parser end callback, limits fields/files to one/two, caps the
request field at 64 KiB and each part's accumulated headers at 16 KiB, and
accepts only `request`, `source_file`, and `watermark_file` with strict field
versus file types and no duplicates. Starlette's 1 MiB `SpooledTemporaryFile`
threshold is retained. The route checks the parser-reported file size against
the 50 MiB contract before one bounded materialization read.

Raw capture, FormData, every published UploadFile, and parser-tracked partial
file are one cleanup domain. Cleanup runs on success, auth rejection, invalid
JSON/multipart, validation failure, service exception, cancellation, and disk
failure. It attempts every close even if an earlier close fails, then
propagates the first cleanup failure. Temporary-file create/write/short-write
and multipart-spool failures map to a stable 503 ingress-unavailable response;
an accepted multipart upload spool that later fails on read maps to the same
stable 503; payload overrun remains `413 auth.payload_too_large`.

Three Nginx configurations add one exact
`= /v1/runtime/media-derivatives` location with `client_max_body_size 52m`.
The exact location keeps the existing upstream and production public-runtime
timeouts/rate limit, adds a dedicated 2 requests/second burst-4 request zone,
a two-connection per-client limit, an eight-connection route-wide budget, and a
60-second body timeout. Rate and connection rejections explicitly return 429.
Global body limits remain unchanged.

The runtime production chain is Caddy to the production Nginx proxy. Caddy
sets `X-Real-IP` from its own connection's `remote_host`; production Nginx
trusts that value only when the immediate proxy is the runtime Compose Caddy
address `172.28.0.11`, then uses the recovered `$binary_remote_addr` for the
per-client zones. Nginx is pinned to `172.28.0.10`, the only forwarded proxy
address trusted by the runtime API. Development and the standalone domain
template receive clients directly and therefore do not enable
forwarded-address rewriting.

## Why Two Disk I/O Passes

Multipart requests intentionally perform two disk I/O passes: network to the
sealed raw spool, then raw spool to multipart file spools. Parsing during the
network pass would reveal malformed multipart before HMAC authorization or
require trusting parser state that was not bound to a sealed evidence object.
Keeping the raw spool lets authorization use the digest of the exact bytes
later parsed, preserves auth-before-parser-error ordering, and bounds memory.

The accepted route may still materialize one validated source and watermark to
bytes because P3-B2 does not change the existing media derivative service
contract. Removing that final materialization is separate B3 work.

## Alternatives Considered

### Trust `Content-Length` and parse the live request stream

Rejected. `Content-Length` may be missing or false, and live parsing cannot
both preserve auth-before-parse behavior and prove the parsed bytes match the
signed digest without a sealed replay source.

### Pass an arbitrary precomputed digest directly from the route

Rejected. That permits future callers to separate digest evidence from the
bytes later parsed. The authorization seam accepts only an evidence loader;
the media capture object owns both evidence production and replay.

### Keep `request.body()` for the 51 MiB application limit

Rejected. It preserves whole-request memory pressure and leaves multipart
file spooling irrelevant because the complete body is already resident.

### Add a new upload service or object-storage dependency

Deferred. P3-B2 is a transport hardening of the existing route. The current
FastAPI, local temporary filesystem, and local-volume artifact store are
sufficient; a new runtime, queue, S3/MinIO service, or media API would expand
scope without solving the immediate signed-ingress problem.

## Consequences

- Multipart ingress trades additional local disk I/O and temporary capacity
  for bounded memory, deterministic cleanup, and stronger signature binding.
- Proxy buffering remains enabled by default; Nginx applies the outer transfer
  guard while the application still enforces authoritative counted bytes.
- Invalid required auth headers, stale timestamps, inactive or unknown
  site/keys, and denied scopes fail before a large media upload. With
  syntactically valid headers and active admission, an actual payload overrun
  is rejected before cryptographic signature comparison; valid-sized malformed
  multipart is parsed only after authentication. Timestamp and database truth
  are checked again after body capture.
- The 52 MiB exact proxy allowance is coupled to the application maximum of
  51 MiB; configuration validation prevents the application from advertising
  a larger accepted body.
- WordPress remains the only owner of review, approval, media-library writes,
  object assignment, publication, and canonical local audit.

## Rollback

Revert the evidence loader, media ingress helper, route wrapper, exact proxy
locations, tests, and this ADR together. No database downgrade, artifact
migration, or stored-data repair is required. Rollback restores the former
whole-body implementation and therefore also restores its memory and parser
cleanup risks.
