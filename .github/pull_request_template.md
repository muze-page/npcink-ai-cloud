## Summary

- Briefly describe the intended change.

## Scope

- Focused module:
- Explicit non-goals:
- Cloud boundary impact:

## Release Gate

- [ ] This PR does not commit production secrets, SMTP passwords, provider keys, DB credentials, or internal tokens.
- [ ] This PR does not make Cloud a WordPress write owner, second ability registry, second workflow registry, or second local control plane.
- [ ] The narrowest useful verification gate is listed below.

## Verification

```text

```

## Production Promotion

Complete only when this PR targets `production`.

- [ ] Source branch is `master` or a release-fix branch that will be backported to `master`.
- [ ] `master` CI is green, or this is an emergency release fix.
- [ ] Rollback path is known.
- [ ] `deploy/RELEASE_CHECKLIST.md` has no newly relevant unchecked blocker for this release scope.
- [ ] Approved for production validation by operator.
