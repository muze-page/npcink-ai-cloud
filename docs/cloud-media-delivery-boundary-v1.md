# Cloud Media Delivery Boundary v1

Status: B4B2 implemented
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

## Active B4B1/B4B2 Contract

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
- no audio/video processor expansion in B4B2; and
- no deletion of audio generation, provider/run/usage/entitlement evidence, or
  the temporary audio `MediaArtifact` result path.

## B4B2 Closeout

B4B1 implemented the replacement contract and prevented new producers or
projection outlets from publishing legacy delivery URLs. B4B2 removes the old
authenticated derivative download, public-token download, permanent
audio-asset promote/playback routes, token helpers, model, configuration, and
dead metric writer. Cloud now exposes one media byte-delivery path: the
site-bound signed pull and transfer ACK above.

The audio-generation capability remains active. It produces a short-lived
audio `MediaArtifact` with provider, run, usage, entitlement, and result
metadata evidence. WordPress will pull that artifact through the unified
contract, verify bytes and checksum locally, present review, and perform any
approved import under local governance. Cloud provides no permanent audio
asset, playback URL, player, or CMS write surface.

## Pre-GA Deployment Reset

Migration `20260715_0063` is intentionally destructive and fail-closed. If
`audio_assets` contains any row, upgrade stops with an explicit pre-GA reset
error. Before retrying, the operator must enter a maintenance window, confirm
that the deployment has no user data to retain, explicitly clear the legacy
rows, and reset the old audio-asset artifact volume so copied storage objects
cannot remain orphaned. The migration does not guess filesystem or object-store
paths from database rows.

After that explicit reset, upgrade drops the empty table. Downgrade recreates
only the empty B4B1-era table shape; it cannot restore deleted rows or bytes.
Historical migrations `0046` and `0061` remain unchanged as migration evidence.

The retained derivative `artifact_download_count` schema/API field is not
canonical delivery truth and no longer receives writes from the removed route.
B4B3 must either derive unified delivery observations from
`MediaArtifactDelivery` or remove the projection through an explicit migration
and UI/API contract change. B4B2 does not broaden into that observability
refactor.

See [ADR-011](decisions/011-signed-pull-media-delivery-ack.md).
