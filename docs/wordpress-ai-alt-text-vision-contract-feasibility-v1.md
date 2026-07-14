# WordPress AI Alt Text Vision Contract Feasibility v1

Status: Cloud runtime implemented; addon real-attachment advertisement and
smoke pending.
Updated: 2026-07-14.

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
- `data_classification`: `public_reference_media` by default.

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

## Bounded Operation Request

The `wordpress_operation.v1` scene request requires at least one bounded visual
reference plus display context. When both URL fields are present, `image_url`
is selected; `thumbnail_url` is used only when `image_url` is absent:

- `prompt`;
- `image_url` or `thumbnail_url`;
- `mime_type` from the image allowlist;
- `filename`, `title`, `existing_alt`, and `existing_caption`;
- `locale`;
- bounded output parameters accepted by the typed operation.

Cloud accepts an allowlisted HTTP(S) URL or a bounded image data URL in the
typed URL field. A data URL is validated for total size, media type, and
encoding before provider preparation. This does not make raw Base64 a public
field: `base64`, `b64`, `b64_json`, `image_base64`, and `image_data` remain
forbidden in the WordPress operation contract.

The public operation also rejects:

- provider keys, WordPress credentials, cookies, nonces, auth headers,
  callback secrets, and signed header fields;
- unbounded visual references and raw byte fields;
- connector-envelope or final-write controls inside the scene request;
- generic chat `messages`, tools, function calls, streams, and
  conversation/thread identifiers.

Provider adapters may translate the validated typed operation into their
provider-specific image input shape. That private adapter translation does not
expand the public operation contract.

## Provider And Result Shape

For a Responses-style provider, Cloud builds bounded `input_text` and
`input_image` parts, applies the alt-text token limit, and records
`suggestion_only=true` in provider metadata. The normalized connector result
contains the WordPress operation identity and output text under
`cloud_connector_result.v1`, plus ordinary run/provider evidence.

No attachment metadata update, media import, caption write, or featured-image
write occurs in Cloud.

## Verified Cloud Evidence

Current Cloud tests prove:

- `alt_text_suggest` resolves to `wp-ai.alt-text-vision`;
- missing or invalid visual references fail closed;
- bounded HTTP(S) and image data URLs reach typed provider image input;
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

- a real attachment is projected through the current connector envelope;
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
