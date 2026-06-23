# Npcink Naming Reset Closeout - 2026-06-24

Status: accepted local closeout record.

This document summarizes the repository, package, route, ability namespace, and
local workspace cleanup completed during the Npcink naming reset. It is intended
as a handoff note for future development so new work starts from the current
canonical paths and does not revive retired Magick AI identifiers.

## Final Development Baseline

Current primary repositories:

| Area | Canonical local path | Default branch |
| --- | --- | --- |
| Cloud service | `/Users/muze/gitee/npcink-ai-cloud` | `master` |
| Cloud Addon | `/Users/muze/gitee/npcink-cloud-addon` | `master` |
| Abilities Toolkit | `/Users/muze/gitee/npcink-abilities-toolkit` | `master` |
| Governance Core | `/Users/muze/gitee/npcink-governance-core` | `master` |
| AI Client Adapter | `/Users/muze/gitee/npcink-ai-client-adapter` | `master` |
| Toolbox | `/Users/muze/gitee/npcink-toolbox` | `master` |
| Eval Lab | `/Users/muze/gitee/npcink-eval-lab` | `main` |

Do not use `/Users/muze/gitee/npcink-governance-core-primary-site-docs`; that
temporary linked worktree was removed so Core development can use the simpler
`/Users/muze/gitee/npcink-governance-core` path.

## Completed Naming Work

- Cloud package and route identity now use Npcink names, including the callback
  namespace `/npcink/open/v1`.
- Eval Lab repository, local folder, package identity, constants, and active PHP
  prefixes were reset to `npcink-eval-lab`, `npcink/eval-lab`,
  `NPCINK_EVAL_LAB_*`, and `npcink_eval_*`.
- Caller repositories were updated to consume current Npcink repository and
  package names.
- Toolbox legacy menu slug compatibility was removed.
- Cloud active docs were cleaned so they no longer point at the old
  `magick-ai-eval-lab` path/name.
- A strict naming residual allowlist was added in Cloud to distinguish active
  identity residue from intentional historical evidence.
- Abilities Toolkit now records the direct ability namespace reset:
  `magick-ai/*` ids are invalid for new active runtime paths, and no alias layer
  should be added during this development phase.

## Completed Compatibility Cleanup

- Cloud Addon no longer imports from the retired
  `magick_ai_cloud_addon_settings` option.
- Cloud Addon uninstall cleanup no longer targets the retired option name.
- Cloud Addon WordPress.org review helper functions now use current Npcink
  helper prefixes.
- Cloud local-alpha smoke configuration now uses `NPCINK_CLOUD_*` environment
  keys instead of `MAGICK_AI_*` keys.
- Cloud task contract and anti-drift checks now use the current
  `pnpm run smoke:local-alpha` gate instead of the retired
  `pnpm --dir magick-ai ...` workspace path.
- Cloud plugin observability labels no longer strip the retired `magick-ai-`
  prefix.

## Workspace Cleanup

- The physical Eval Lab repository was renamed from
  `/Users/muze/gitee/magick-ai-eval-lab` to
  `/Users/muze/gitee/npcink-eval-lab`.
- GitHub repository remote for Eval Lab now points to
  `https://github.com/muze-page/npcink-eval-lab.git`.
- Temporary acceptance clone directories were removed:
  - `/Users/muze/gitee/npcink-governance-core-acceptance-clone`
  - `/Users/muze/gitee/npcink-ai-client-adapter-acceptance-clone`
- Detached acceptance worktrees were removed with `git worktree remove`:
  - `/Users/muze/gitee/npcink-governance-core-acceptance`
  - `/Users/muze/gitee/npcink-ai-client-adapter-acceptance`
- Core path was normalized back to
  `/Users/muze/gitee/npcink-governance-core`.
- The old local Core branch `codex/npcink-governance-core-rename` was deleted
  after confirming it was contained by `master`.
- The temporary Core stash for `.sisyphus/session-breadcrumb.md` was dropped.
- The old Gitee remote was removed from the local `npcink-cloud-addon` clone so
  future pushes use GitHub `origin` only.

## Intentionally Preserved

- `https://magick-ai.local/` remains the primary local WordPress deployment and
  test site. It is a site name, not an active package, repository, route, or
  ability namespace residue.
- `/Users/muze/Local Sites/magick-ai/app/public` remains the matching primary
  local WordPress path for acceptance work.
- Historical archive docs and migration evidence may still mention retired
  Magick AI names. Do not rewrite archive records only to make history look
  current.
- The old `magick-ai/*` ability ids may appear only in explicit migration maps
  or historical evidence that states they are retired. They must not be used in
  new active runtime calls.
- Commerce add-on ids such as `magick-ai/wc-*` were not migrated in this pass;
  they need a separate owner decision.
- `/Users/muze/gitee/magick-ai-root` is still retained because some historical
  boundary and contract references are useful during review.

## Remaining Non-Blocking Cleanup Candidate

`/Users/muze/gitee/npcink-eval-lab-local-untracked-before-canonical-main-20260624`
is still present. It is about 125 MB and contains old untracked Eval Lab
generated artifacts, mainly image-generation evaluation outputs and CSV/JSON
records. It does not affect current development. Remove it only when the
generated evidence is no longer needed.

## PRs Merged During This Closeout

- `npcink-ai-cloud` PR #14: canonical Npcink plugin IDs.
- `npcink-ai-cloud` PR #15: router callback namespace `/npcink/open/v1`.
- `npcink-ai-cloud` PR #16: active Cloud docs cleanup for Eval Lab naming.
- `npcink-ai-cloud` PR #17: naming residual allowlist.
- `npcink-ai-cloud` PR #18: active Cloud naming residual cleanup.
- `npcink-eval-lab` PR #7: Eval Lab code and package identity reset.
- `npcink-eval-lab` PR #8: Eval Lab internal prefix cleanup.
- Caller updates:
  - `npcink-abilities-toolkit` PR #70
  - `npcink-governance-core` PR #39
  - `npcink-ai-client-adapter` PR #20
  - `npcink-toolbox` PR #21
  - `npcink-cloud-addon` PR #3
- `npcink-toolbox` PR #22: remove legacy Toolbox menu slug compatibility.
- `npcink-cloud-addon` PR #4: remove Cloud Addon legacy option compatibility.

## Verification Snapshot

The following verification was run during the closeout:

- `npcink-eval-lab`: `composer check`, `composer test`, and
  `composer check:callers`.
- `npcink-cloud-addon`: `composer test:all` and `composer check:wporg`.
- `npcink-ai-cloud`: `pnpm run check:anti-drift`,
  `pnpm run test:anti-drift`,
  `uv run pytest tests/contract/test_task_contract_geo_routing.py -q`,
  `pnpm run frontend:type-check`, and `bash -n scripts/local-alpha-smoke.sh`.
- GitHub CI passed for the merged Cloud, Cloud Addon, and Eval Lab PRs.
- Final strict active-file denylist scan found no active matches after excluding
  archive docs, generated artifacts, dependency directories, build outputs, and
  the explicit allowlist document.

## New Feature Start Rule

Start new work from the canonical repository paths above. For Core, use:

```bash
cd /Users/muze/gitee/npcink-governance-core
git switch master
git pull --ff-only
git switch -c codex/<feature-name>
```

For Eval Lab, use `main` instead of `master`.

Do not add compatibility aliases for retired names unless a separate migration
contract explicitly requires them.
