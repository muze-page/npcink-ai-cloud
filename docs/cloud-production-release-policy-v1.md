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

## Required Gates Before `master`

For normal feature and fix PRs:

- describe the focused module and explicit non-goals;
- confirm Cloud boundary impact, especially that Cloud is not becoming a
  WordPress write owner or second local control plane;
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
