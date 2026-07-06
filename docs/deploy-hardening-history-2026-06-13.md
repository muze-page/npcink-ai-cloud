# Deploy And Quality Hardening History - 2026-06-13

Status: project history, closeout summary, and operator handoff.

This document records the June 2026 quality and deploy hardening work for the
standalone Npcink AI Cloud repository. It summarizes what was found, what was
fixed, what was verified, and what still requires external operator action.

It is intentionally a history document. It does not define a new runtime
contract, control plane, provider registry, workflow registry, or WordPress
write owner.

## Boundary

The work stayed inside the Cloud deploy, quality, runtime hardening, and
frontend bundle surfaces.

Cloud remains the hosted runtime and detail surface. WordPress remains the
control plane for local settings, abilities, approval, editing, publishing, and
final object mutation. The changes did not add a second control plane or move
WordPress-owned decisions into Cloud.

## Timeline

- `bcc32d8 Fix cloud quality baseline drift`
  - Restored the Python type and quality baseline.
  - Hardened upstream provider and callback response handling.
  - Updated stale README commands and frontend handoff checks.
- `0fdb611 Preserve portal member proxy header`
  - Preserved `x-npcink-portal-member-ref` through the portal proxy.
- `ef84647 Update cloud feature base guidance`
  - Removed stale feature-base guidance that referenced a nonexistent
    `codex/cloud-hardening-base` worktree.
- `e78b0e9 Fix deploy bundle smoke without frontend image`
  - Made the deploy-bundle smoke path usable when the frontend image is
    intentionally skipped.
- `43a8b3e docs: clarify cloud metadata projection boundary`
  - Clarified metadata projection boundary documentation in the current branch
    history.
- `b72b8a6 Stabilize frontend deploy bundle build`
  - Fixed the full frontend image build from the standalone Cloud workspace.
  - Added SSH preflight diagnostics before expensive deploy work starts.

## Problems Found And Fixed

### Quality baseline drift

`mypy app` reported errors in the web search service and commercial service
mixins. The fixes added explicit typing for Tavily API-key selection, aligned
commercial mixin inheritance, and narrowed optional values before use in the
portal and admin mixins.

The baseline also had stale README examples from the older monorepo layout.
Those examples were updated to standalone Cloud commands and paths.

### Runtime upstream response hardening

Raw upstream provider errors and callback response bodies could carry more data
than needed into error messages or logs.

The OpenAI adapter, Anthropic adapter, and router performance snapshot worker
now truncate upstream error and callback response bodies before surfacing them.
Focused tests cover those truncation paths.

### Frontend handoff checks

The frontend handoff and scope check scripts previously failed when invoked
without a `--handoff` argument, which made the default quality loop noisier than
necessary.

Those scripts now print usage and exit successfully when no handoff file is
provided, while still enforcing checks when a handoff path is supplied.

### Portal proxy contract

The portal proxy did not preserve `x-npcink-portal-member-ref`, which risked
breaking contract expectations for member-scoped portal calls.

The proxy shared header allowlist now includes that header, and the frontend
portal proxy contract test covers the behavior.

### Feature base guidance

README guidance still pointed at a nonexistent
`codex/cloud-hardening-base` worktree. That made future branching guidance
ambiguous.

The approved base is now the synced standalone Cloud `master` branch.

### Deploy bundle smoke without frontend image

The deploy smoke path needed to support backend-focused checks when the
frontend image was intentionally skipped. Before the fix, nginx still expected
the static frontend upstream.

The production nginx config now uses Docker DNS resolution and a runtime
frontend proxy variable so it can start without a frontend container. Remote
smoke skips buyer-home and portal-login page checks only when
`NPCINK_CLOUD_SKIP_FRONTEND_IMAGE=1`, while API, internal, and runtime checks
continue to run.

The smoke flow also defaults `NPCINK_CLOUD_ENVIRONMENT=test` for local replay
so sample provider configuration can work without real production keys.

### Full frontend deploy bundle build

The frontend image build failed in the standalone Cloud workspace because the
Docker build context did not include the root workspace manifests needed by
pnpm.

The production compose file now builds the frontend image from the repository
root with `frontend/Dockerfile`. The Dockerfile copies the root workspace
manifests, installs with the pinned `pnpm@10.33.0`, builds the `frontend`
workspace, and starts `node frontend/server.js`. A root `.dockerignore` keeps
the larger context bounded.

Contract tests lock the workspace install behavior.

### SSH deploy preflight

Remote deploy attempts could spend time preparing artifacts before discovering
that the SSH target was not usable.

`deploy/deploy-to-ssh-host.sh` now checks that the configured identity file
exists and performs a non-interactive SSH reachability preflight with
`BatchMode=yes` and a connection timeout before bundle build, upload, seed, or
smoke work begins.

## Verification Evidence

The following checks passed during this hardening pass:

- `make baseline`
- `make lint-changed`
- `.venv/bin/mypy app`
- `.venv/bin/ruff check .`
- `.venv/bin/python -m pytest -q`
- `.venv/bin/python -m pytest tests/api tests/contract tests/domain -q`
- `pnpm run test:anti-drift`
- `pnpm run check:perimeter`
- `pnpm --dir frontend run lint`
- `pnpm --dir frontend run type-check`
- `pnpm --dir frontend run test:unit`
- `pnpm --dir frontend run test:i18n-contract`
- `pnpm --dir frontend run test:portal-proxy-contract`
- `pnpm --dir frontend run test:admin-dev-autologin-contract`
- `docker compose -f docker-compose.prod.yml config`
- `NPCINK_CLOUD_SKIP_FRONTEND_IMAGE=1 pnpm run check:e2e:deploy-bundle:smoke`
- `pnpm install --frozen-lockfile`
- `docker compose -f docker-compose.prod.yml build frontend`
- `pnpm run check:e2e:deploy-bundle:smoke`

The full deploy-bundle smoke passed after the frontend build fix, including
frontend image build, image load, service start, and page smoke checks.

The SSH preflight was also exercised with:

```bash
set -a
source deploy/workspace-target.env.sh
set +a
bash deploy/deploy-to-ssh-host.sh --skip-bundle-build --skip-seed --skip-smoke
```

It now fails fast with a clear missing-key diagnostic instead of continuing
into later deploy work.

## Remaining External Blockers

The remaining blockers are outside the repository code.

### Missing SSH identity file

The configured identity file is still absent:

```text
../../config/key/Magick_AI.pem
```

It was not found in the checked fallback locations:

- `../../config/key/Magick_AI.pem`
- `../config/key/Magick_AI.pem`
- `/Users/muze/gitee/config/key/Magick_AI.pem`
- `/Users/muze/config/key/Magick_AI.pem`

A full search under `/Users/muze` for `Magick_AI.pem` also returned no result.

### SSH port reachability

The target SSH port did not respond during the local reachability probe:

```bash
nc -vz -G 10 114.132.150.46 22
```

The probe timed out. A real remote deploy still requires an operator to provide
the expected SSH key and make the target host reachable on port 22 from the
current network.

Current workspace target update, 2026-07-06:

- The old host `114.132.150.46` is no longer the active workspace target.
- The current production host is `120.24.237.214`.
- The current production public origin is `https://cloud.npc.ink`.
- Passwords, SSH keys, production tokens, provider keys, DB credentials, and
  `.env.deploy` remain operator-held secrets and must not be committed.

## Current Operator Handoff

The repository-side work is complete for the problems found in this pass.

Before attempting a real remote deploy again, an operator should:

1. Place the correct SSH key at the path exported by
   `NPCINK_CLOUD_DEPLOY_SSH_KEY`, or update `deploy/workspace-target.env.sh` to
   point at the correct key.
2. Confirm the remote host accepts SSH from the current network.
3. Re-run the deploy preflight:

```bash
set -a
source deploy/workspace-target.env.sh
set +a
bash deploy/deploy-to-ssh-host.sh --skip-bundle-build --skip-seed --skip-smoke
```

After the preflight succeeds, continue with the normal release checks and
remote deploy flow from `deploy/RELEASE_CHECKLIST.md`.

## Guidance For Future Agents

- Treat the external SSH key and port reachability issues as operator
  prerequisites, not repo defects.
- Keep deploy smoke behavior covered by contract tests when changing
  `docker-compose.prod.yml`, `frontend/Dockerfile`, nginx production config, or
  deploy scripts.
- Do not reintroduce monorepo `cloud/` path assumptions into standalone Cloud
  docs or scripts.
- Keep Cloud runtime and deploy changes inside the existing boundary: Cloud can
  execute hosted runtime work and expose diagnostics, but WordPress remains the
  control plane and final write owner.
