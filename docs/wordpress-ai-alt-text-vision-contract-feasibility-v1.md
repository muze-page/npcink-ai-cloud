# WordPress AI Alt Text Vision Contract Feasibility v1

Status: accepted, Cloud runtime implemented.
Date: 2026-07-07.

## Context

The WordPress AI plugin exposes `ai/alt-text-generation` as a vision-capable
text generation ability. The current Cloud addon correctly does not advertise a
vision-capable text model because the WordPress AI Connector path only exposes
the Cloud scene text model and the Cloud scene image generation model.

Cloud already has enough runtime foundation to make the capability feasible:

- content generation boundaries allow media alt text and caption suggestions as
  reviewable suggestions;
- generic hosted vision data handling is documented as allowed when the caller
  sends only the smallest image reference or visual context needed;
- provider adapters already support `vision` execution through the Responses
  style payload shape;
- Image Context Evidence already builds bounded `input_image` / `image_url`
  provider payloads for visual inspection;
- WordPress AI Connector routing already has managed runtime profiles for text,
  classification, image generation, and audio generation.

The remaining integration risk is addon-side evidence quality: WordPress must
send Cloud a fetchable image reference and bounded media context without making
the addon a write owner or a second control plane.

## Decision

Support for WordPress AI alt text should be implemented as a dedicated
WordPress AI Connector vision runtime contract, not as a fake text-model
capability and not as an addon-side workaround.

The intended routing shape is:

| Routing intent | Profile ID | Execution kind | Plugin tasks |
| --- | --- | --- | --- |
| `media.alt_text_vision` | `wp-ai.alt-text-vision` | `vision` | `alt_text_suggest` |

This profile is a Cloud runtime binding only. It is not a Cloud ability
registry, prompt editor, approval policy, media-library writer, or model
selection control plane.

## Minimum Runtime Contract

The first implementation should extend the existing WordPress AI Connector
runtime input rather than adding a separate public API.

Required public runtime posture:

- `ability_name`: `npcink-cloud/wp-ai-connector`
- `contract_version`: `wp_ai_connector_runtime.v1`
- `channel`: `wordpress_ai_connector`
- `execution_pattern`: `inline`
- `storage_mode`: `result_only` or stricter
- `data_classification`: `public_reference_media` by default, or `pii` with
  `no_store` when the image may identify a person
- `source_surface`: `wordpress_ai_connector`
- `connector_id`: `npcink-cloud`
- `task`: `alt_text_suggest`
- `write_posture`: `suggestion_only`
- `direct_wordpress_write`: `false`
- `no_conversation`: `true`

The `request` object may include only bounded visual reference fields:

- `prompt`: short local ability prompt or textual media context
- `image_url`: public or short-lived signed image URL
- `thumbnail_url`: optional smaller public or short-lived signed image URL
- `mime_type`: allowlisted image MIME type
- `filename`: bounded display context
- `title`: bounded display context
- `existing_alt`: bounded display context
- `existing_caption`: bounded display context
- `locale`: optional output locale

The implementation must reject:

- provider keys, WordPress credentials, cookies, nonces, auth headers, callback
  secrets, or signed header fields;
- private admin media URLs that the upstream provider cannot fetch safely;
- arbitrary base64 image payloads in the WordPress AI Connector public runtime
  path for the first implementation;
- multiple image inputs for one alt-text suggestion;
- final write controls such as `update_attachment_metadata`,
  `wordpress_write_policy`, `final_write_target`, or `apply_policy`;
- generic chat `messages`, tools, web search, function calling, streaming, and
  conversation/thread identifiers.

## Provider Payload Shape

Cloud should reuse the existing vision provider pattern instead of inventing a
new adapter shape.

For Responses-style providers, build:

```json
{
  "input": [
    {
      "role": "user",
      "content": [
        {
          "type": "input_text",
          "text": "Generate concise WordPress image alt text. Return only the alt text."
        },
        {
          "type": "input_image",
          "image_url": "https://example.test/path/image.jpg"
        }
      ]
    }
  ],
  "params": {
    "temperature": 0,
    "max_tokens": 48,
    "max_output_tokens": 48
  },
  "metadata": {
    "source_surface": "wordpress_ai_connector",
    "task": "alt_text_suggest",
    "suggestion_only": true
  }
}
```

Chat-style provider fallback may use the existing `messages` image URL shape
only inside Cloud's provider adapter boundary. The public runtime input should
stay scene-contract based and must not accept generic `messages`.

## Output Contract

The Cloud result should remain text-only and suggestion-only:

```json
{
  "contract_version": "wp_ai_connector_result.v1",
  "task": "alt_text_suggest",
  "output_text": "Concise alt text suggestion.",
  "suggestion_only": true,
  "direct_wordpress_write": false,
  "provider": "openai",
  "model_id": "vision-capable-model",
  "run_id": "run_..."
}
```

No attachment metadata update, media import, caption write, or featured-image
write may happen in Cloud.

## Required Implementation Steps

1. Move `alt_text_suggest` out of `wp-ai.short-text` and into a dedicated
   `wp-ai.alt-text-vision` profile with `execution_kind=vision`.
2. Extend `validate_wordpress_ai_connector_runtime_contract()` so
   `alt_text_suggest` requires one safe image reference and rejects generic chat
   or write-control fields.
3. Extend the WordPress AI Connector provider input builder so
   `alt_text_suggest` emits bounded vision input instead of text-only input.
4. Ensure provider connection routing can select only configured provider
   connections whose model allowlist includes a callable vision-capable model.
5. Update addon-side WordPress AI model exposure only after Cloud contract and
   tests pass. The addon should then advertise a real vision-capable model
   rather than reusing the text model.
6. Extend the addon smoke gate to run `ai/alt-text-generation` only when a real
   attachment and vision profile are available.

## Verification Gate

The implementation is not done until these checks exist and pass:

- unit or domain tests that `alt_text_suggest` routes to
  `wp-ai.alt-text-vision`;
- contract tests that missing image reference fails closed;
- contract tests that `messages`, credentials, write controls, and base64
  image payloads are rejected;
- provider-input tests that Cloud sends `input_image` or the provider-specific
  equivalent;
- runtime tests that the result remains `suggestion_only` and
  `direct_wordpress_write=false`;
- addon smoke that proves `ai/alt-text-generation` succeeds with a real
  attachment and does not update attachment metadata.

Recommended narrow Cloud gate:

```bash
.venv/bin/python -m pytest tests/api/test_wordpress_ai_connector_runtime.py
```

Before cross-repo closeout:

```bash
pnpm run check:fast
```

## Non-Goals

- No Cloud media-library write.
- No Cloud attachment metadata update.
- No prompt, preset, router, approval, or ability enablement UI in Cloud.
- No new public endpoint.
- No arbitrary base64 upload in the WordPress AI Connector path.
- No second WordPress control plane.

## Current Recommendation

Proceed only after the addon and WordPress AI plugin can supply a safe image
reference for the ability run. Until then, keep `ai/alt-text-generation`
discoverable but do not advertise Cloud as a vision-capable WordPress AI text
model.
