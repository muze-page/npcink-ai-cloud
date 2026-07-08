# WordPress AI Editor Runtime Closeout - 2026-07-07

Status: historical closeout record.

Purpose: summarize the WordPress AI editor, alt text vision, and text scene
runtime stage across `npcink-ai-cloud` and `npcink-cloud-addon`.

## Background

The work started from the local WordPress AI consumer surface at:

```text
https://magick-ai.local/wp-admin/options-general.php?page=ai-wp-admin
https://magick-ai.local/wp-admin/upload.php?page=generate-image
```

The product goal was not to build a new Cloud editor or a second WordPress
control plane. The goal was to make the existing WordPress AI consumer able to
use the Cloud hosted runtime through the addon bridge while preserving the
local WordPress/plugin truth boundary.

The practical target was:

- Cloud owns hosted runtime execution, provider routing, result detail, usage
  evidence, and fail-closed runtime validation.
- `npcink-cloud-addon` owns the WordPress bridge, signed runtime call, local
  model exposure, and repeatable smoke gate.
- WordPress AI remains the local consumer surface.
- WordPress writes remain local, reviewable, and outside Cloud ownership.

## Boundary Decisions

The stage stayed within the current content-generation boundary:

- media alt text and caption suggestions are allowed as reviewable
  suggestions;
- text scene outputs are allowed when routed through the hosted runtime
  contract;
- all WordPress AI Connector outputs stay `suggestion_only`;
- Cloud must not update attachment metadata, create posts, publish content,
  approve proposals, or become prompt/router/ability truth.

The dedicated alt text vision path is documented in:

```text
docs/wordpress-ai-alt-text-vision-contract-feasibility-v1.md
```

The runtime contract posture is:

```text
ability_name: npcink-cloud/wp-ai-connector
contract_version: wp_ai_connector_runtime.v1
channel: wordpress_ai_connector
task: alt_text_suggest
write_posture: suggestion_only
direct_wordpress_write: false
no_conversation: true
```

## Implemented Cloud-Side Behavior

Cloud landed the runtime side through PR 106:

```text
https://github.com/muze-page/npcink-ai-cloud/pull/106
merge commit: 8b6b60430149843e8778293807f236e1d1472b47
```

The merged Cloud commit series was:

- `e838281a Document WordPress AI alt text vision contract`
- `fc0c4414 Add WordPress AI alt text vision routing`
- `07e78d0e Support WordPress AI alt text media fallbacks`
- `ad0cac39 Tighten WordPress AI text scene outputs`
- `ded565d7 Fix OpenAI provider import ordering`

Important Cloud-side outcomes:

- `alt_text_suggest` is treated as a vision-capable WordPress AI Connector
  runtime path, not as a fake text-only model.
- text scene output contracts were tightened for WordPress AI consumers;
- provider input construction supports bounded visual reference handling;
- unsafe public runtime input remains rejected rather than converted into a
  generic chat/messages interface;
- results remain text-only suggestions with no WordPress write authority.

The final `ded565d7` commit was a CI fix only. It corrected Ruff import
ordering in `app/adapters/providers/openai.py` after GitHub backend CI rejected
the first PR run.

## Implemented Addon-Side Behavior

The addon bridge side landed through PR 27:

```text
https://github.com/muze-page/npcink-cloud-addon/pull/27
merge commit: 0dddb980ae021783a8178f6e6e556f106db3618a
```

The merged addon commit series was:

- `3560758 Add WordPress AI alt text vision adapter`
- `f64c4e0 Inline local WordPress AI alt text media`
- `e136336 Add WordPress AI editor smoke gate`

Important addon-side outcomes:

- the WordPress AI adapter can expose the Cloud-backed alt text vision path
  only after the Cloud contract exists;
- local media context is inlined as bounded runtime evidence for the Cloud
  request;
- the addon gained a repeatable smoke gate:

```bash
composer run smoke:wp-ai-editor
```

The smoke gate proves the WordPress AI editor path through the addon without
making the addon a Cloud runtime owner or a WordPress write bypass.

## Local WordPress Verification

Local smoke testing used the development WordPress site:

```text
https://magick-ai.local
```

The admin test surfaces were:

- WordPress AI settings page:
  `wp-admin/options-general.php?page=ai-wp-admin`
- image generation page:
  `wp-admin/upload.php?page=generate-image`
- post editor smoke path through generated draft content.

The repeated smoke work created three temporary local drafts:

```text
285893
285999
286000
```

They were deleted after verification, and each ID was rechecked with WP-CLI.
The final verification for all three was:

```text
Could not find the post with ID ...
```

This cleanup was local-development only. It did not affect production data and
did not require a Cloud deployment.

## Verification And Merge

Cloud verification included:

```bash
pnpm run check:fast
composer quality:matrix:run
git diff --check
.venv/bin/ruff check .
```

GitHub PR 106 checks passed after the import-order fix:

- PR body contract: passed
- Secret scan: passed
- classify: passed
- frontend: passed
- backend: passed
- CodeQL: passed
- Analyze (python): passed
- Analyze (javascript-typescript): passed

Addon verification included:

```bash
composer run test:all
composer run smoke:wp-ai-editor
git diff --check
composer quality:matrix:run
```

GitHub PR 27 checks passed:

- PHP contracts: passed
- PR body contract: passed

Direct pushes to `master` were rejected by GitHub branch protection for both
repositories. The work was therefore published through PR branches and merged
normally after required checks passed:

```text
npcink-ai-cloud:    codex/wp-ai-text-scene-20260707
npcink-cloud-addon: codex/wp-ai-editor-smoke-20260707
```

After merge, local `master` was fast-forwarded to `origin/master` in both
repositories.

## Repository State Notes

At closeout:

- `/Users/muze/gitee/npcink-ai-cloud` was clean on `master...origin/master`.
- `/Users/muze/gitee/npcink-cloud-addon` was clean on `master...origin/master`.
- `/Users/muze/gitee/npcink-abilities-toolkit` was inspected read-only on
  `codex/ability-implementation-posture` and showed no uncommitted diff.

No Gitee push or production deploy was performed.

## Boundary Conclusion

This stage is complete because it connected the WordPress AI consumer path to
Cloud runtime capability without moving ownership boundaries:

- Cloud stayed runtime/detail only.
- Addon stayed the WordPress bridge and consumer adapter.
- WordPress AI stayed the local consumer UI.
- WordPress writes and final application remained local/governed.
- No second ability registry, workflow registry, prompt registry, or WordPress
  control plane was introduced.

## Suggested Next Stage

The next useful stage should be a focused consumer-surface audit rather than a
new Cloud feature:

- run WordPress AI editor and image-generation smoke paths against representative
  local media and post-editor cases;
- compare the addon-exposed model labels, source labels, and error messages
  against actual Cloud runtime/provider responses;
- add only narrow smoke or contract coverage for gaps that are observed in the
  real WordPress consumer flow;
- avoid expanding Cloud admin, Portal, or addon settings surfaces unless a
  named runtime/read contract already exists.

The purpose of that next stage is to reduce integration ambiguity for real
WordPress consumers while keeping Cloud from becoming the product control plane.
