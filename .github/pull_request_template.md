## Summary

- Briefly describe the intended change.

## Scope

- [ ] This change is limited to the stated Cloud module.
- [ ] Public runtime API, capability contract, provider seam, deployment lifecycle, or product boundary docs were updated if changed.
- [ ] No unrelated generated files, local environment files, screenshots, or cross-repo worktree changes are included.
- Focused module:
- Explicit non-goals:
- Cloud boundary impact:

## Release Gate

- [ ] This PR does not commit production secrets, SMTP passwords, provider keys, DB credentials, or internal tokens.
- [ ] This PR does not make Cloud a WordPress write owner, second ability registry, second workflow registry, or second local control plane.

## Cloud Boundary

- [ ] Cloud remains the hosted runtime enhancement layer.
- [ ] Runtime results stay suggestion-only unless an explicit governed downstream contract owns the write.
- [ ] This does not add a second WordPress control plane, local ability registry, workflow registry, approval/preflight/audit truth, or WordPress write owner.
- [ ] This does not move prompt/router/preset local truth into Cloud-facing WordPress control surfaces.
- [ ] Provider credentials, request logs, usage, and entitlement evidence remain redacted from logs and responses.

## Verification

- [ ] The narrowest useful verification gate is listed below.
- [ ] `pnpm run check:fast`
- [ ] `pnpm run check:perimeter` if runtime boundaries, WordPress seams, or provider surfaces changed.
- [ ] `pnpm run check:anti-drift` if Cloud frontend/backend contracts changed.
- [ ] `pnpm run lint` if Python typing, lint-sensitive code, or shared backend modules changed.

```text

```

## Risk

- Residual risk:
- Rollback plan:

## Deployment Impact

- [ ] No production deployment impact.
- [ ] Requires production environment approval after CI passes on the protected production branch.

## Production Promotion

Complete only when this PR targets `production`.

- [ ] Source branch is `master` or a release-fix branch that will be backported to `master`.
- [ ] `master` CI is green, or this is an emergency release fix.
- [ ] Rollback path is known.
- [ ] `deploy/RELEASE_CHECKLIST.md` has no newly relevant unchecked blocker for this release scope.
- [ ] Approved for production validation by operator.

## Notes

Summarize the behavior change, boundary decision, and known follow-up.
