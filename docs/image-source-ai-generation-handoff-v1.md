# Image Source AI Generation Handoff v1

Status: active.

Cloud image source results may advertise AI image generation as a manual
runtime handoff. This keeps stock-image suggestions and generated-image
candidates separate while letting the local product surface expose an
`AI generate` action beside image-source candidates.

## Boundary

- Cloud image source runtime returns stock/reference candidates and handoff
  metadata only.
- Cloud image generation runtime may generate image candidates.
- WordPress media import, featured image assignment, insertion, and publication
  stay in local Core/plugin approval and write flows.
- The handoff must not include provider secrets, WordPress credentials, final
  write controls, or raw prompt/control truth owned by the local UI.

## Phase 1: Manual Action

`image_source_candidates` results include:

- `ai_generation_handoff`
- `handoff.available_actions[]`

The action uses:

- `ability_name`: `npcink-cloud/generate-image`
- `contract_version`: `image_generation_request.v1`
- `profile_id`: `grok-imagine-image-quality`
- `execution_kind`: `image_generation`
- `trigger`: `manual_user_action`

The handoff provides `input_defaults`, but it intentionally requires the local
UI to provide `prompt`. The local UI may derive that prompt from the original
image-source query, post title, excerpt, selected text, or user edits.

## Phase 2: Assisted Prompt

The local UI may prefill the prompt from article or product context, but the
user must still click generate. Cloud should continue to receive only the
approved runtime request and must not become prompt/preset truth.

Phase 2 handoff includes `prompt_prefill_plan`:

- `mode`: `local_context_prefill`
- `owner`: `local_plugin_ui`
- `requires_user_review`: `true`
- `source_priority`: local-only source ordering for prompt assembly
- `local_prompt_fields`: bounded sections such as subject, context,
  composition, style, and constraints
- `assembly`: section order and joiner
- `safety`: `do_not_autorun`, `do_not_include_secrets`, and
  `direct_wordpress_write=false`

The local UI should use this plan to build an editable prompt draft. It should
not call `npcink-cloud/generate-image` until the user confirms the prompt.
The Cloud image-source result must not include the raw prompt draft.

## Phase 3: Batch

Batch image generation requires higher trust and explicit quotas:

- plan entitlement
- per-site concurrency
- per-run item limits
- cost guardrails
- visible review before WordPress writes

Phase 3 handoff includes `batch_generation_plan`:

- `mode`: `local_reviewed_batch_plan`
- `owner`: `local_plugin_control_plane`
- `requires_entitlement`: `true`
- `requires_user_review`: `true`
- `requires_per_item_prompt_review`: `true`
- `max_items_per_user_action`: bounded by Cloud handoff metadata
- `write_owner`: `local_wordpress_approval_flow`
- `direct_wordpress_write`: `false`
- `do_not_autorun`: `true`

The current recommended execution pattern is to submit reviewed generation
items as explicit runtime requests. Future `whole_run_offload` may be used only
after the local control plane supplies a reviewed batch plan and Cloud
entitlement/concurrency checks pass.

Batch remains a runtime enhancement, not an autopublish path.
