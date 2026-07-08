# Cloud Ability-Model Routing v1

Status: active.
Date: 2026-06-29

## Context

WordPress plugins need a maintainable way to map similar AI tasks to hosted
model runtime profiles. Title generation, excerpt generation, SEO metadata, and
media alt text are different plugin abilities, but they share similar runtime
needs: short output, low latency, bounded cost, and suggestion-only results.

Cloud already owns hosted model catalog, routing profiles, provider execution,
usage, entitlement, health, diagnostics, and service-plane audit evidence. The
WordPress/plugin side remains the control plane for ability definitions,
prompts, approvals, preflight, audit truth, and final WordPress writes.

## Decision

Use **ability-model routing** as the Cloud admin concept for plugin-facing
runtime model bindings.

An ability-model route is a small, stable routing group that maps one or more
plugin tasks to a Cloud runtime profile and model-instance binding. It is not a
Cloud ability registry, plugin feature switch, prompt editor, approval policy,
or WordPress write configuration.

Current WordPress AI Connector routing groups are:

| Routing intent | Profile ID | Execution kind | Plugin tasks |
| --- | --- | --- | --- |
| `content.short_text` | `wp-ai.short-text` | `text` | `excerpt_generation`, `meta_description`, `title_generation`, `audio_summary_script` |
| `content.editorial` | `wp-ai.editorial` | `text` | `comment_reply_suggest`, `content_rewrite`, `content_summary` |
| `content.classification` | `wp-ai.classification` | `text` | `comment_moderation`, `content_classification` |
| `media.alt_text_vision` | `wp-ai.alt-text-vision` | `vision` | `alt_text_suggest` |
| `media.image_generation` | `wp-ai.image-generation` | `image_generation` | `image_generation` |

The WordPress AI alt-text ability needs a real image reference plus bounded
textual context; Cloud must not satisfy it by advertising a text-only model as
vision-capable. The implementation contract is tracked in
[WordPress AI Alt Text Vision Contract Feasibility v1](wordpress-ai-alt-text-vision-contract-feasibility-v1.md).

## Ownership

Cloud may own and expose:

- `profile_id`
- `routing_intent`
- `group_id`
- `execution_kind`
- candidate model instance bindings
- `timeout_ms`
- `allow_fallback`
- `max_retries`
- routing revision, status, and operator note
- runtime health, provider/model evidence, usage, and service-plane audit

WordPress/plugin side continues to own:

- ability identity, schema, and permission metadata
- plugin ability enablement
- prompt and preset truth
- local approval, preflight, and audit truth
- final WordPress object writes
- site-local adoption of any Cloud routing recommendation

## Boundary Rules

- Cloud must consume plugin/runtime contract artifacts; it must not invent a
  second ability, workflow, prompt, preset, or router truth.
- Public runtime policy ingress remains allowlisted to runtime-plane fields.
- Ability-model routing rows must remain shared routing groups by default.
  Plugin-specific or site-specific overrides require a separate boundary
  review before persistence is added.
- Candidate model instances must come from enabled, configured provider
  connections whose `model_ids` allowlist includes the candidate `model_id`.
  A model that exists only in the hosted catalog but is not enabled on the
  provider connection must not appear as selectable, must not be persisted by
  the admin routing endpoint, and must not be used by runtime resolution.
- Provider catalog sync should treat the supplier's authenticated model-list
  endpoint as the source of callable `model_id` truth. Local metadata,
  `models.dev`, and provider-specific rules may enrich official IDs with
  feature, price, context, type, and runtime-instance hints, but they must not
  invent callable model candidates that the supplier account did not return.
- New plugin tasks should first map into an existing routing intent. Create a
  new routing intent only when real runtime evidence shows materially different
  latency, cost, output shape, storage, or execution-kind needs. `alt_text_suggest`
  is the current exception because it changes the execution kind from text to
  vision and requires bounded image-reference validation.
- Cloud-native runtime abilities may have read-only projections in Admin, but
  they must not duplicate plugin task rows such as title generation, SEO
  metadata, taxonomy suggestions, or WordPress write workflows.

Forbidden fields in ability-model routing persistence:

- `ability_enabled`
- `prompt`
- `preset`
- `approval_policy`
- `apply_policy`
- `final_write_policy`
- `final_write_target`
- `wordpress_write_policy`
- `wordpress_write_target`
- `requires_confirm`
- `required_scope`
- `tool_policy`

## Admin Surface

The existing Admin URL remains:

```text
/admin/ability-models
```

The preferred product label is **Ability-model routing** / **能力-模型路由**.
The page may configure WordPress AI Connector runtime routing groups and show
Cloud-native runtime ability projections. The page must continue to state that
plugin switches, prompts, approvals, and final WordPress writes stay in the
local plugin path.

## Verification

Use the narrowest relevant checks for this surface:

```bash
.venv/bin/python -m pytest tests/api/test_wordpress_ai_connector_runtime.py
node frontend/tests/unit/admin-ai-resources-contract.mjs
```

Before cross-repo closeout or production promotion, also run the repository's
standard fast gate:

```bash
pnpm run check:fast
```

For production Cloud smoke verification after deploy, use:

```text
docs/production-wordpress-ai-connector-smoke-runbook-v1.md
```
