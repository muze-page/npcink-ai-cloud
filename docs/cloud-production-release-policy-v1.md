# Cloud Production Release Policy v1

Status: active lightweight gate.

Purpose: define the low-cost production release rules for the current early
validation phase. This policy is a human/process gate until GitHub branch
protection and environment approval are worth paying for.

## Scope

This policy covers changes that may reach `https://cloud.npc.ink`.

It does not create a second WordPress control plane, approval system, ability
registry, workflow registry, prompt truth, provider secret store, or runtime
policy authority. Cloud remains the hosted runtime/service-plane layer.

## Branch Model

- `master` is the development integration branch.
- `production` is the production release source.
- feature and fix branches merge to `master` first.
- production releases are promoted from `master` to `production`.

Do not directly edit production application code on the server. Server-side
changes are limited to runtime secrets in `.env.deploy` and emergency
break-glass fixes that must be backported to Git immediately.

Branch divergence is expected: `production` records the deployed release while
`master` continues development. A production-only patch must not remain an
unexplained long-term fork. Before the next promotion, classify it as already
equivalent on `master`, forward-port it to `master`, or document why the old
deployment behavior is obsolete. Do not merge the accumulated `production`
history back into `master` merely to make the branch graph look aligned.

## Pre-refactor Production Reconciliation

The production-only patches below were reconciled against development
`master` on 2026-07-14. Their behavior is present in the current development
line with contract coverage, so no reverse merge or duplicate cherry-pick is
required:

- `9aca0dc0`: deployment workflows call the SSH deploy script directly;
- `9c160ed5`: remote deploy arguments are shell-quoted;
- `5a2cf130`: production proxy preserves forwarded host/protocol headers;
- `6dff10a5`: ready probes derive the required host/origin headers;
- `559e032f`: `/terms` resolves the static terms entrypoint and is smoke-tested;
- `4e532f0c`: admin bootstrap is routed directly to the API with forwarded origin;
- `c9f3036b`: frontend runtime backend variables are not frozen into the build.

This is a semantic reconciliation record, not a claim that the two branch
histories or trees should be identical.

## Required Gates Before `master`

For normal feature and fix PRs:

- describe the focused module and explicit non-goals;
- confirm Cloud boundary impact, especially that Cloud is not becoming a
  WordPress write owner or second local control plane;
- keep public legal and policy pages under `site/terms/*` in the production
  static release path when those pages change;
- state explicitly when needed: Cloud is not becoming a WordPress write owner;
- run the narrowest useful local gate, or explain why GitHub CI is the gate;
- keep production secrets, SMTP passwords, provider keys, DB credentials, and
  internal tokens out of Git.

Recommended command:

```bash
pnpm run check:release-policy
```

## Required Gates Before `production`

Before promoting `master` to `production`:

- `master` CI is green;
- the promotion contains only intended release changes;
- `deploy/RELEASE_CHECKLIST.md` has no newly relevant unchecked blocker for the
  release scope;
- no direct server code edit is being used as source truth;
- public static legal pages, including `/terms/en/terms.html`, remain covered
  by the deploy smoke when the release changes legal, policy, or proxy files;
- rollback path is known before merging;
- production secrets remain server-side or in GitHub Secrets, not committed.

For the current early validation phase, the manual sign-off is:

```text
Approved for production validation by operator.
```

Put that sentence in the production promotion PR body until paid branch
protection/environment approval is enabled.

## Deployment Rule

Merging or pushing to `production` runs GitHub Actions:

```text
Cloud CI backend + frontend -> deploy-production -> cloud.npc.ink
```

The manual `Deploy Production` workflow is a fallback only. It must be run from
the `production` branch.

If a `production` push changes only public static legal/policy content under
`site/terms/*`, the static terms fast path may update the current release
without rebuilding Docker images, running migrations, refreshing providers, or
restarting runtime services. This exception is limited to static terms content;
proxy, compose, application, runtime, provider, database, and workflow changes
must use the full production deploy path.

## Emergency Rule

If production is broken and SSH hotfixing is unavoidable:

1. record the command or file changed;
2. verify `https://cloud.npc.ink/health/live`;
3. backport the fix to Git before the next deploy;
4. note whether rollback is still possible from the previous release.

## Upgrade Trigger

Move from this lightweight policy to enforced GitHub branch protection and
environment approval when any of these become true:

- production has meaningful external users;
- more than one person can merge or deploy;
- paid customers or credits are active;
- production incidents would create material support or trust cost.
