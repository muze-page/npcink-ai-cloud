# WordPress AI Alt Text Vision Contract Feasibility v1

Status: Cloud artifact-referenced runtime implemented; addon upload handoff,
real-attachment advertisement, and smoke pending.
Updated: 2026-07-15.

## Current State

Cloud implements `alt_text_suggest` as a WordPress typed operation carried by
the one neutral connector runtime. The implemented outer request is:

- `site_id`: authenticated Cloud site identity;
- `ability_name`: `npcink-cloud/connector-runtime`;
- `contract_version`: `cloud_connector_runtime.v1`;
- `channel`: `editor`;
- `execution_kind`: `vision`;
- request profile alias: `text.balanced`;
- `execution_pattern`: `inline`;
- `storage_mode`: `result_only`;
- `data_classification`: `internal` by default.

The neutral `input` envelope contains:

- `site_url`;
- `platform_kind=wordpress`;
- `connector_id=npcink-cloud-addon`;
- `connector_version`;
- `suggestion_only=true`;
- a `wordpress_operation.v1` operation contract whose task is
  `alt_text_suggest`.

The request-time `text.balanced` profile is an admitted connector alias, not
the execution truth for the operation. Managed routing projects the durable
run and provider request to `wp-ai.alt-text-vision`, with routing intent
`media.alt_text_vision` and vision execution semantics.

## Ownership Boundary

The WordPress/plugin side owns Ability exposure, attachment selection,
permissions, review, approval, audit, and the final attachment metadata write.
Cloud owns only hosted vision execution, provider routing, bounded result
normalization, and run/provider/usage evidence.

Cloud returns a text suggestion through `cloud_connector_result.v1`. It does
not update attachment metadata, import media, set captions, set featured
images, or claim that a local write occurred.

## Artifact-referenced Operation Request

The `wordpress_operation.v1` scene request requires one site-scoped visual
reference plus bounded display context:

- `prompt`;
- `source_artifact_id`;
- `filename`, `title`, `existing_alt`, and `existing_caption`;
- `locale`;
- bounded output parameters accepted by the typed operation.

Cloud resolves the reference only within the authenticated site. It requires
an available, unpurged, unexpired JPEG, PNG, or WebP image within the dedicated
vision byte budget. Unknown and cross-site artifact IDs have the same not-found
posture. Resolve and new execute admission check metadata without reading the
object. Actual execution revalidates the metadata and performs an integrity-
checked bounded read immediately before provider preparation.

The active operation rejects `image_url`, `thumbnail_url`, caller `mime_type`,
data URLs, storage keys, and raw Base64 fields including `base64`, `b64`,
`b64_json`, `image_base64`, and `image_data`.
There is no compatibility request shape.

The scene request uses an exact canonical field allowlist:
`source_artifact_id`, `prompt`, `filename`, `title`, `existing_alt`,
`existing_caption`, `locale`, and `max_tokens`. Unknown, duplicate, aliased,
case-variant, and whitespace-variant field names fail closed. Inline media
transport detection is recursive, so hiding a data URL or Base64 image marker
inside a nested value does not create a second input path.

`prompt` must be a nonempty string of at most 500 characters. `filename` and
`title` are optional strings of at most 160 characters;
`existing_alt` and `existing_caption` are optional strings of at most 240;
`locale` is an optional string of at most 32; and `max_tokens` is an optional
non-Boolean integer from 1 through 96. These values are normalized once at the
contract boundary. Containers and coercible string/float/Boolean substitutes
fail before run creation, queue encryption, or provider execution.

The public operation also rejects:

- provider keys, WordPress credentials, cookies, nonces, auth headers,
  callback secrets, and signed header fields;
- unbounded visual references and raw byte fields;
- connector-envelope or final-write controls inside the scene request;
- generic chat `messages`, tools, function calls, streams, and
  conversation/thread identifiers.

Only the private provider-preparation edge translates verified artifact bytes
into a transient provider-specific image input. The bytes and transient data
URL are representation-safe and never enter run input, encrypted queue input,
result, callback, or log contracts. That private translation does not expand
the public operation contract.

## Provider And Result Shape

For a Responses-style provider, Cloud builds bounded `input_text` and
`input_image` parts from the verified source, applies the alt-text token limit,
and records `suggestion_only=true` in provider metadata. Vision HTTP failures
are canonicalized so upstream error echoes cannot persist source bytes or
prompt context. Successful provider output is also fail-closed: the operation
payload is projected to bounded `output_text` only, nested raw provider fields
are discarded, and selected text containing inline media transport is
rejected. The normalized connector result contains the WordPress operation
identity and that text-only payload under `cloud_connector_result.v1`, plus
ordinary run/provider evidence.

No attachment metadata update, media import, caption write, or featured-image
write occurs in Cloud.

## Verified Cloud Evidence

Current Cloud tests prove:

- `alt_text_suggest` resolves to `wp-ai.alt-text-vision`;
- missing, cross-site, expired, unavailable, oversized, or invalid image
  artifacts fail closed before a provider call;
- verified artifact bytes reach typed provider image input only through the
  private preparation edge;
- execute replay succeeds before current source revalidation, while new and
  queued execution revalidate the artifact;
- public responses, durable run input, result, callback, and object
  representations contain no inline image bytes or data URL;
- request field aliases/case variants and recursively nested inline media are
  rejected before persistence or provider execution;
- allowed fields reject wrong JSON types and out-of-range values before a run
  or encrypted execution input can exist;
- successful provider raw/nested echoes are discarded, while inline media in
  selected output text fails closed;
- legacy HTTP(S), data-URL, caller-MIME, and raw-Base64 request forms are
  rejected;
- raw Base64 fields, generic chat, credentials, and write controls are
  rejected;
- the run remains vision-scoped and the result remains suggestion-only;
- RuntimeService delegates WordPress-specific preparation and normalization to
  the WordPress operation module.

Recommended narrow Cloud gate:

```bash
.venv/bin/python -m pytest tests/api/test_wordpress_ai_connector_runtime.py
```

## Pending Addon Evidence

The Cloud runtime implementation does not complete the end-user feature by
itself. The addon and WordPress AI consumer still need operator-observed
evidence that:

- a real attachment is uploaded through the current media ingress and its
  `source_artifact_id` is projected through the connector envelope;
- the addon advertises the vision capability only when the complete local and
  Cloud path is available;
- `ai/alt-text-generation` returns a reviewable suggestion;
- no attachment metadata changes before local review and approval.

Until that real-attachment advertisement and smoke evidence exists, this
document must not be cited as cross-repository or production closeout.

## Non-Goals

- No Cloud media-library write.
- No Cloud attachment metadata update.
- No prompt, preset, router, approval, or Ability enablement UI in Cloud.
- No new public endpoint.
- No raw Base64 request field or generic chat proxy.
- No second WordPress control plane.
