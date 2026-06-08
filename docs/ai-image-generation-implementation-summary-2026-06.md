# AI Image Generation Implementation Summary - 2026-06

Status: implemented and verified.

Date: 2026-06-09

Scope:

- Cloud repo: `/Users/muze/gitee/magick-ai-cloud`
- Toolbox repo: `/Users/muze/gitee/magick-ai-toolbox`
- Local WordPress editor: `https://magick-ai.local/wp-admin/post.php?post=5824&action=edit`

This document records the implementation history for the hosted AI image
generation flow, including the Cloud runtime, Toolbox editor UX, media SEO
normalization, and Core/Adapter adoption boundary.

## Final Product Shape

AI image generation is implemented as a hosted runtime capability, not as a
second WordPress control plane.

The expected editor flow is:

1. Operator selects a paragraph or opens image recommendations from the editor.
2. Toolbox opens the image-source modal in recommendation mode.
3. Cloud image-source planning uses article context and related content to
   return public image candidates plus visual direction candidates.
4. Operator clicks `使用方向`.
5. Toolbox switches to manual AI prompt mode with an editable prompt.
6. Operator chooses aspect ratio, quality, and candidate count, then clicks
   `AI 生成配图`.
7. Cloud runs the hosted image generation runtime through the
   `grok-imagine-image-quality` profile.
8. Toolbox displays generated-image candidates as `image_candidate.v1`.
9. Operator reviews media SEO fields and sends the selected candidate through
   Adapter/Core for import or featured-image adoption.

Final media import, featured-image assignment, and WordPress writes remain
local/Core-governed.

## Boundary Decisions

- `image_sources` remains a search/browse flow.
- AI image generation is a separate `image_generation` runtime execution kind.
- Cloud may host provider adapters, routing profiles, usage/quota details, and
  runtime diagnostics.
- Cloud must not become a second ability registry, workflow registry, prompt
  truth, media registry, or WordPress write owner.
- Toolbox may assemble and display reviewable prompts from local editor context,
  but the operator must explicitly confirm generation.
- AI-generated image candidates are suggestion-only until Core/Adapter handles
  the governed media write path.
- Runtime responses preserve `hosted_profile` and `model_id` so UI labels can be
  honest and stable.

## Cloud Work Completed

The Cloud side now supports hosted AI image generation through the existing
runtime plane:

- Added/used an image generation endpoint variant in the provider adapter.
- Routed image generation to the exact `grok-imagine-image-quality` hosted
  profile.
- Kept AI generation separate from image-source search.
- Added LLM-level image prompt planning for richer visual direction candidates.
- Preserved `hosted_profile` and `model_id` in runtime output for downstream UI.
- Fixed provider routing so the image profile resolves to the expected provider
  instead of a generic fallback.
- Fixed catalog refresh revision collisions by using a unique
  timestamp-plus-UUID style revision.
- Added Cloud prompt direction metadata so Toolbox can present direction cards.

Relevant Cloud commits:

- `b232077 Add LLM image prompt planner`
- `a576bb1 Route image generation to exact Grok profile`
- `a518481 Fix image catalog refresh and provider routing`
- `7a92f71 Improve image prompt direction metadata`

## Toolbox Work Completed

The Toolbox editor image modal now supports a reviewable AI image generation
workflow:

- Added AI-generated image candidates to the existing image recommendation
  modal.
- Added mode controls for recommended image search vs manual AI prompt.
- Added user-facing options for aspect ratio, quality, and candidate count.
- Added paragraph/article-context prompt prefill from Cloud direction candidates.
- Changed empty recommendation search to automatically use article context
  instead of showing a validation error.
- Fixed misleading source labels. Generated candidates show stable hosted
  profile/model metadata when available instead of hardcoded `grok imagine`.
- Added source and provider details in the inspector.
- Added regeneration controls for selected AI-generated candidates.
- Ensured stale selected-image and adoption state is cleared when the operator
  switches from a source candidate to an AI prompt direction.
- Moved prompt direction cards out of collapsed Cloud diagnostics so `使用方向`
  is reliably clickable.

Relevant Toolbox commits:

- `3a03650 Increase image source runtime timeout`
- `9be7d3c Stabilize AI prompt direction selection`
- `727fc27 Normalize AI image media SEO fields`
- `9456ca9 Keep AI prompt directions clickable`

## Media SEO Normalization

A specific regression was found after AI generation worked: the generated
candidate title, ALT, and description could look like prompt instructions, for
example:

- `Create an original editorial image for...`
- `Create a publication-safe editorial illustration...`
- `Source context: ...`
- `Visual task: ...`
- `Composition: ...`

The normalization fix now:

- treats prompt/instruction-like text as unsuitable for media SEO fields;
- uses bounded article context and selected paragraph context as the preferred
  basis;
- preserves the generation prompt separately as generation evidence;
- records `seo_suggestions.basis = reviewed_article_context`;
- keeps media title, ALT, and description reviewable before Core adoption.

Verified browser output after the fix:

- Title: article title.
- ALT: Chinese editorial-image ALT derived from the article title.
- Description: AI-generated article image candidate description requiring human
  review before import or featured-image adoption.
- No prompt instructions appear in media SEO field values.

## UI Issues Found And Fixed

### Missing AI Entry Point

The user initially could not find an AI image entry point in the image check
surface. The flow was clarified so AI generation is available in the image
recommendation modal and Cloud Checks includes direct image generation smoke
coverage.

### Runtime Cost Quota Exhaustion

Cloud image-source and generation calls can fail when runtime cost quota is
exhausted. The remediation is operational: raise or reset the Cloud runtime
cost quota. The UI now surfaces Cloud business errors instead of rendering empty
candidates.

### Misleading Source Label

The UI previously showed labels such as `来源：grok imagine`, which could be
historical or ambiguous. The fixed behavior uses stable `hosted_profile` and
`model_id` metadata where available and falls back to a generic `AI generated`
label.

### Empty Recommendation Search

An empty manual image recommendation search now falls back to article-context
recommendations rather than blocking the operator with an empty-query error.

### Direction Card Click Instability

The direction cards were first rendered as full clickable cards, then changed to
explicit action buttons. A later browser run showed they were still inside
collapsed Cloud details, so DOM coordinates could be present while clicks
landed on image cards below. The final fix renders direction cards in normal
document flow and keeps only lower-frequency diagnostics collapsed.

## Verification Summary

Cloud-side verification included provider/catalog/runtime tests and browser
flows through the local WordPress editor.

Toolbox-side verification included:

- `node --check assets/editor-content-support.js`
- `php tests/run.php`
- `composer smoke:ai-image-media-seo`
- `composer validate --no-check-publish --no-check-all`
- `git diff --check`
- Browser verification:
  - recommendation modal opens from the editor;
  - Cloud visual directions appear;
  - `使用方向` is clickable;
  - modal switches to manual AI prompt mode;
  - generated candidate appears;
  - selected generated candidate shows media SEO fields derived from article
    context, not prompt instructions.

The latest checked state had both `magick-ai-cloud` and `magick-ai-toolbox`
worktrees clean after commits.

## Operational Notes

- AI image generation depends on Cloud runtime quota. Quota exhaustion should be
  handled by Cloud quota/billing operations, not by adding local provider keys
  to Toolbox.
- Generated image URLs may be temporary. Candidates carry persistence/risk
  metadata and should be adopted promptly or regenerated before Core approval.
- Public stock image search and AI image generation should remain visibly
  distinct in UI and contracts.
- Related content and selected paragraph context are useful for prompt planning,
  but final generation remains operator-triggered.

## Follow-Up Ideas

These are optional improvements, not blockers for closing the implementation
thread:

- Add quota/usage warnings near AI generation controls before quota exhaustion.
- Add style presets for common article image types.
- Add a cheaper preview/draft quality mode for exploration.
- Feed accepted/rejected image feedback into Cloud eval dashboards.
- Add image-quality comparison across multiple generated candidates.
- Add a clearer retry path for temporary provider URLs close to expiry.

