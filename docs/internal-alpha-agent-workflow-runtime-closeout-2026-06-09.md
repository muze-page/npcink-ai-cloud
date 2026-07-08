# Internal Alpha Agent/Workflow Runtime Closeout

Status: stage closeout.

Date: 2026-06-09

## Scope

This note records the closeout for the recent Cloud Admin/Portal Agent/Workflow
metadata and hosted runtime validation work.

The stage covered:

- Cloud-side read-only Agent/Workflow metadata display and validation.
- Backend metadata projection consolidation for Web Search and Media workflows.
- Provider to runtime to result to usage/error evidence in the real local target
  environment.
- CI baseline repair and local CI-equivalent verification.
- Hosted text routing profile follow-up for `text.ai`.

## What Shipped

### Agent/Workflow Metadata

Cloud now keeps shared Agent/Workflow metadata in a backend read-only registry
instead of duplicating static frontend definitions.

The useful shape is:

- Admin display reads the same Cloud registry.
- Portal projection reads the same Cloud registry.
- Tests assert the same backend truth.
- Web Search and Media workflow UI metadata no longer need separate static
  copies per surface.

This is intentionally metadata/detail only. It does not make Cloud a workflow
engine, Agent platform, or second ability registry.

### Runtime Evidence Chain

The real local target environment was validated across:

- provider catalog and provider health;
- runtime execution;
- run result retrieval;
- usage summary and usage meter;
- provider error evidence;
- callback delivery error evidence.

Evidence files:

```text
/Users/muze/gitee/npcink-cloud/.tmp/local-alpha-smoke/evidence-codex-provider-runtime-20260609103557.json
/Users/muze/gitee/npcink-cloud/.tmp/local-alpha-provider-failure-drill/evidence-codex-provider-runtime-20260609103507.json
/Users/muze/gitee/npcink-cloud/.tmp/local-alpha-callback-failure-drill/evidence-codex-provider-runtime-20260609103514.json
```

Important fixes discovered during validation:

- OpenAI-compatible provider catalog now classifies BGE models such as
  `BAAI/bge-m3` as `embedding`, not text.
- Latency probe rollup skips retired/missing catalog instances instead of
  making operational readiness fail.
- Local alpha smoke no longer assumes a single hardcoded model id by default.
- Local alpha smoke records result and usage-meter evidence in the evidence
  JSON.
- The smoke script now finds the current WordPress Cloud addon settings route.

### Hosted Text Profile

`text.ai` was added as the stable hosted text entry profile for product callers.
It is documented separately in:

```text
docs/text-ai-hosted-routing-profile-v1.md
```

The key rule is that `text.ai` is a hosted routing profile, not a model name.
Current runtime state may resolve it to `gpt-5.5`, but callers must not treat
that model id as the durable product contract.

### CI Baseline

The remote repository is Gitee:

```text
git@gitee.com:gitgreat/npcink-ai-cloud.git
```

At closeout, Gitee CI status was not directly observable from the local machine:

- Gitee commit status API returned `404`.
- Gitee `/actions` and `/pipelines` returned `404`.
- The repository page returned `403` without an authenticated browser session.
- GitHub CLI could not query Actions because the repository has no GitHub
  remote.

Because the remote status could not be queried, the local CI-equivalent baseline
from `.github/workflows/ci.yml` was run instead.

Verified commands:

```bash
pnpm run test:anti-drift
make bootstrap-dev
.venv/bin/ruff check .
.venv/bin/mypy app
.venv/bin/python -m pytest tests/api tests/contract tests/domain -q
pnpm --dir frontend run lint
pnpm --dir frontend run type-check
pnpm --dir frontend run test:i18n-contract
pnpm --dir frontend run test:portal-proxy-contract
pnpm --dir frontend run test:admin-dev-autologin-contract
```

Observed result:

```text
backend pytest: 429 passed, 5 skipped, 1 warning
```

CI baseline fixes made during closeout:

- `make bootstrap-dev` now uses `pnpm --dir frontend install --frozen-lockfile`
  so frontend lockfile verification matches the actual frontend package.
- Usage rollup tests compute expected profile and instance rollup counts from
  the current seeded catalog instead of hardcoding stale counts.

## Boundary Conclusion

Cloud stayed inside the approved hosted runtime/detail boundary:

- Local WordPress/plugin remains the product control plane.
- Local side still owns final enablement, approval, and WordPress writes.
- Cloud only owns hosted runtime, catalog/profile metadata, diagnostics,
  usage, callback dispatch evidence, and bounded Admin/Portal detail surfaces.
- No Cloud skill marketplace, Cloud MCP platform, Cloud OpenClaw platform, or
  second workflow engine was added.
- No new infrastructure was introduced.

This stage follows the same stop rule used elsewhere in the Cloud contracts:
Cloud may provide read-only metadata and hosted execution enhancement, but must
not become a second truth source for abilities, workflows, prompts, presets, or
WordPress writes.

## Commit Trail

Relevant commits at closeout:

```text
f2631a4 Stabilize CI bootstrap baseline
2bcb943 Unpin text.ai hosted model selection
6e9e6b6 Add text.ai hosted routing profile
ffc0d14 Validate provider runtime evidence chain
a06a700 Make CI baseline blocking
8090eb6 Fix CI baseline checks
```

There is also a local documentation commit:

```text
584b8c4 Document text.ai hosted routing contract
```

## Remaining Risks

- Gitee private CI status still needs confirmation from an authenticated Gitee
  UI or account context.
- The runtime evidence files are local artifacts, not durable release artifacts.
  If they need to become release evidence, copy their summarized contents into a
  release checklist or operator note.
- Provider catalog contents are dynamic. Tests should avoid pinning exact model
  ids unless the test is specifically about a named profile contract.
- `text.ai` is now the stable product-facing hosted text entry point, but local
  callers must still send `execution_kind=text` and preserve governed handoff
  behavior.

## Recommendation

Pause feature development at this point.

Resume only when one of these is true:

- Gitee CI is confirmed and has a concrete failure to fix.
- A focused follow-up smoke is needed for Toolbox hosted content support using
  `profile_id=text.ai` and `execution_kind=text`.
- A release note or operator evidence package is required.

Avoid expanding this work into new Agent/Workflow product surfaces until the
current runtime and metadata baseline has stayed green in the target CI
environment.
