# Cloud Media Delivery Boundary v1

Status: B4B1 implemented; B4B2 legacy-route removal pending
Date: 2026-07-15
Scope: WordPress-first Cloud runtime, with a platform-neutral delivery seam

## Boundary

Cloud owns short-lived media bytes, verified artifact metadata, signed transfer,
delivery evidence, acknowledgement evidence, retention shortening, and transfer
diagnostics. The local CMS connector owns the user permission check, preview,
review, import, association, publication, final write, and canonical local audit.

This is a Cloud runtime contract, not a WordPress API. Future Typecho, Z-BlogPHP,
Ghost, or other connectors may use the same contract without creating a
platform-by-channel adapter matrix. B4B1 does not implement those connectors.

## Active B4B1 Contract

Public media result envelopes contain only an artifact reference and verified
metadata. They do not contain a download URL, public token, signed query,
provider URL, Base64 payload, data URL, or storage key. Current public result
projection removes those historical credential-bearing fields from exact known
media envelopes without rewriting durable run evidence.

The local connector pulls bytes with:

```text
GET /v1/runtime/media/artifacts/{artifact_id}/download
```

The request requires normal public HMAC authorization, `runtime:read`, and a
nonce under the dedicated `media_pull` replay policy. Query parameters,
`Idempotency-Key`, and byte ranges are rejected. Artifact IDs must match the
canonical `art_<32 lowercase hex>` shape. Cross-site and missing artifacts are
both `404`; unavailable artifacts are `409`; expired or purged artifacts are
`410`; and missing or mismatched stored bytes fail closed.

Application rejection evidence records only whether a query was present, never
its value. Edge access logs use an URI-only format that omits request queries,
arguments, and referrers. The production proxy network is pinned and supplies
the same CIDR used by the API's trusted-forwarder setting, preserving real
per-client replay and rate-limit scopes.

Cloud performs an exact metadata preflight, creates a `MediaArtifactDelivery`
row, commits that evidence, and streams without full-body buffering. The edge
uses an exact GET-only regex location, `proxy_buffering off`, a dedicated
5 requests/second per-IP rate zone with burst 10, and independent per-IP/global
connection limits of 4/16. The production generic runtime rate limit remains in
force as an additional guard.

A delivery becomes completed only after normal EOF with the exact expected byte
count and SHA-256. An interrupted, truncated, checksum-mismatched, or oversized
stream remains incomplete. The generator never yields bytes past the expected
length. Platform-neutral delivery completion evidence advances only in the
same successful completion transaction; derivative-specific counters are not
the delivery truth.

The connector acknowledges verified receipt with:

```text
POST /v1/runtime/media/artifacts/{artifact_id}/delivery-ack
```

The request uses ordinary POST HMAC authorization, `runtime:execute`, nonce, and
`Idempotency-Key`. Query parameters are rejected. The strict
`media_artifact_delivery_ack.v1` body contains only `delivery_id`,
`received_byte_size`, and `received_checksum` in addition to its contract
version. ACK requires the same site and artifact, a completed unexpired
delivery, and exact expected facts. The first ACK records transfer-only evidence
and shortens artifact retention to `min(existing expiry, acknowledged time + 5
minutes)`; it never extends retention, deletes bytes, changes artifact status,
or writes to a CMS. Exact key-and-fingerprint replay returns the same evidence;
conflicts return `409`. ACK and purge serialize on the artifact row, and ACK
also rechecks current lifecycle state after acquiring it, so an expired,
purge-pending, or purged artifact cannot be extended or revived.

## Evidence Separation

`ReplayReceipt` remains request replay/rate evidence. `MediaArtifactDelivery`
is separate transfer evidence and records expected facts, start/completion,
ACK deadline, ACK key/fingerprint/trace, verified receipt facts, retention
before/after, expiry, and revocation. Pull request and rejection scopes use
`public_pull_site`, `public_pull_key`, and `public_pull_ip`; they do not consume
or pollute the existing `public_post_*` scopes. Ordinary non-media GET behavior
is unchanged and does not require a nonce.

## Non-goals

- no Cloud push to a CMS or arbitrary site URL;
- no WordPress media-library write, publication, approval, or local audit truth;
- no permanent Cloud media library, CDN, gallery, or resumable/range transfer;
- no compatibility aliases in new result envelopes;
- no audio/video processing expansion in B4B1; and
- no deletion of the legacy `AudioAsset` table in this batch.

## Staged Closeout

B4B1 implements the replacement contract and prevents new producers or
projection outlets from publishing legacy delivery URLs. The old authenticated
artifact download and audio public-token routes remain callable only until
B4B2 removes their routes, token helpers, tests, and residual data fields. New
Cloud or connector code must not call them.

See [ADR-011](decisions/011-signed-pull-media-delivery-ack.md).
