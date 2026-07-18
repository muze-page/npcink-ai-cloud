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
- the frontend does not inherit the backend `.env.deploy`; only its reviewed
  runtime allowlist may be present, and runtime-data encryption secrets must
  remain backend-only;
- a runtime-data encryption key cutover has count-only inventory/dry-run/apply/
  verify evidence, a checksum-verified and restore-tested backup, and the
  matching old code and old key recovery point.

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

`NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET` and
`NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID` are exempt from ordinary
configuration-only rotation. They may change only in a planned maintenance
window using a bundle-backed staged release and its newly loaded API image.
Because the bundle excludes `.env.deploy`, copy it from the protected
shared/current source into the staged directory, install and verify mode `0600`,
and do so before any Compose command. Do not use a general deploy helper that
switches `current` or starts services to prepare this maintenance stage.
Keep production `postgres` and `redis` running while `api`, `worker`,
`callback-worker`, and `ops-worker` are stopped and fenced. Run the ordered
`python -m app.dev.reencrypt_runtime_data` `inventory`, `dry-run`, `apply`, and
new-key-only `verify` phases only through
`docker compose ... run --rm --no-deps --env-from-file`; the untracked
maintenance env must be mode `0600` and contain the target secret/key ID plus an
explicit old root. This path must not depend on host application source or a
host Python environment. The first raw-ciphertext cutover omits `--old-key-id`;
future `rde.v1` rotations must pass each old key ID to `inventory`, then
positionally pair every old root with the same explicit key ID in `dry-run` and
`apply`.
Writers must remain stopped on any failed phase. After verification, start
API/readiness first, then workers/operational readiness, and remove the
maintenance env and temporary old-key material after the rollback-evidence
window. Normal runtime has no legacy or dual-read path; retain the
migration-only tool for future controlled rekeys. Rollback requires the matched
old database backup, old application revision, and old key; a database-only or
key-only rollback is forbidden.

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
