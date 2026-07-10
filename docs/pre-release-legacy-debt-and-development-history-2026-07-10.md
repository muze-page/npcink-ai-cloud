# Pre-release Legacy Debt and Development History - 2026-07-10

Status: active release-readiness handoff.

## 1. Purpose

This document records the reasoning, implementation history, verified gains,
remaining historical debt, and release posture from the pre-release cleanup and
deployment-efficiency work completed before Npcink AI Cloud has external users
who depend on old contracts.

It answers two recurring questions:

1. Which historical compatibility paths have actually been removed?
2. Which remaining `legacy`, `deprecated`, `fallback`, migration, or history
   references are real debt rather than necessary product behavior?

This is a handoff and decision record. Active boundary and release contracts
remain authoritative, especially:

- `docs/cloud-production-release-policy-v1.md`
- `docs/cloud-content-generation-boundary-v1.md`
- `docs/cloud-task-pack-boundary-v1.md`
- `docs/cloud-agent-workflow-metadata-projection-v1.md`
- `docs/cloud-agent-feedback-quality-gate-v1.md`

## 2. First-principles Position

The cleanup work follows these rules.

### 2.1 Remove compatibility before users depend on it

The project is already deployed for production validation, but it does not yet
have an external-user compatibility obligation. A retired alias, route, field,
fallback, or configuration name should therefore be removed now unless there is
a concrete migration requirement.

Do not add a shim merely because an older name once existed. If no user or
external integration depends on it, prefer one canonical contract plus a
regression test proving the old contract is rejected.

### 2.2 Do not confuse history with runtime debt

The following are normally retained:

- Alembic migrations required to reconstruct and upgrade the database;
- historical closeout documents and harvested boundary contracts;
- deprecated-provider-model state used to prevent new selection while
  explaining previously saved selections;
- provider protocol terms such as `openai_compatible` when they describe a
  real current adapter type;
- bounded routing fallback, retry, and database-backed worker recovery that
  remain part of the active runtime contract.

These are evidence, lifecycle, or resilience mechanisms. They are not the same
as accepting an obsolete public contract.

### 2.3 Keep Cloud inside its ownership boundary

Cloud may own hosted execution, provider adapters, usage, entitlement, billing
evidence, health, diagnostics, artifacts, queues backed by PostgreSQL truth,
and read-only runtime metadata projections.

Cloud must not become a second WordPress control plane, ability registry,
workflow registry, prompt/router/preset truth, approval owner, audit truth, or
WordPress write owner. Cleanup and release automation must not be used as a
reason to move those responsibilities into Cloud.

### 2.4 Optimize from evidence, not intuition

Release speed work should first expose where time is spent, then reduce or
parallelize only the measured long pole. Path-aware checks may accelerate pull
requests, but `master` and `production` must continue to run the full release
gate. External QQ, mailbox, and real Alipay account behavior remains an
operator test because deterministic CI cannot prove provider-account state.

## 3. Development History

### 3.1 Naming reset and contract harvest

The Magick AI to Npcink transition removed old product names and aliases from
active runtime paths. Historical contracts were harvested into
`docs/legacy-contracts/magick-ai-root/` so future development could preserve
important boundary decisions without keeping the retired workspace as an
active source tree.

The resulting rule is: historical names may remain in explicit history,
migration evidence, or cleanup-only code, but they must not silently become
accepted aliases for new runtime requests.

### 3.2 Strong contraction and release-readiness cleanup

The Cloud surface was contracted around hosted runtime and bounded service
detail. Task-pack APIs, prompt/preset recommendation ownership, thick Portal
features, stale admin routes, and registry-shaped Agent/Workflow compatibility
fields were removed or retired.

The July release-readiness passes also corrected stale documentation, removed
obsolete test ignores, restored failing contract aggregation, narrowed admin
commercial surfaces, and made current plan-version capacity authoritative over
stale entitlement snapshots.

Relevant records include:

- `docs/release-readiness-legacy-cleanup-closeout-2026-07-02.md`
- `docs/release-readiness-cleanup-closeout-2026-07-07.md`
- `docs/admin-surface-cleanup-closeout-2026-07-02.md`
- `docs/npcink-naming-reset-closeout-2026-06-24.md`

### 3.3 Canonical scope enforcement

The old broad read scope alias was removed from site-key issuance and runtime
authorization. Current behavior requires canonical scopes such as
`runtime:read` and `stats:read`.

Commit `448d42bf` introduced the rejection behavior. PRs `#133` and `#134`
merged and promoted it. Regression tests now prove that old scope aliases are
not accepted:

- `tests/api/test_portal_routes.py::test_portal_issue_site_key_rejects_legacy_scope_aliases`
- `tests/api/test_stats_routes.py::test_stats_routes_reject_legacy_read_scope_alias`

This is the preferred cleanup shape: delete the alias, keep one canonical
contract, and test rejection rather than translation.

### 3.4 Account membership as Portal access truth

Portal access previously allowed a site-level grant to stand in for account
membership. Commit `9d4c1852` removed that fallback. A principal now needs an
active customer-account membership before site access is resolved.

The regression test
`tests/api/test_portal_routes.py::test_portal_site_access_rejects_site_grant_without_account_membership`
records the new fail-closed behavior. This prevents a historical data shape
from becoming a permanent second authorization truth.

### 3.5 GitHub-only release model

GitHub is the only source-control and release target. The local directory name
may still contain `gitee`, but the repository remote and production process are
GitHub-based. Normal Git work uses command-line `git`; `gh` is reserved for
GitHub-specific PR, check, Actions, and API operations.

The branch model is:

```text
feature/fix branch -> master -> production -> cloud.npc.ink
```

Production application code is not edited directly on the server. Server-side
changes are limited to secret/config maintenance and documented emergency
break-glass work that is backported before the next deployment.

### 3.6 Release-flow optimization

The release pipeline was optimized in stages rather than replaced:

- static terms-only changes gained a narrow fast path;
- production release smoke was formalized;
- release timing became a generated job summary and artifact;
- PR backend work became path-aware;
- high-risk changes still escalate to the full backend gate;
- the full backend suite was split into static analysis plus three
  duration-weighted pytest shards;
- one stable aggregate `backend` result remains the release dependency;
- deploy bundles reuse external images and reduce repeated transfer/build work;
- CI Actions and bundle construction were updated without changing the runtime
  stack.

The approach was informed by mature open-source practices from FastAPI,
Sentry, GitHub Actions job summaries, and duration-based pytest splitting. The
project borrowed the pattern, not an entire third-party CI architecture.

The initial monolithic backend gate took roughly 7-8 minutes. The current PR
`#146` full backend run completed with three pytest shards in roughly 3 minutes
each in parallel, while static analysis completed in under a minute. This
reduces backend wall time while retaining the full release evidence.

Timing data remains the basis for future changes. More shards are justified
only if several successful runs show a persistent imbalance. Relevant record:
`docs/release-ci-open-source-patterns-2026-07.md`.

### 3.7 Existing-stack observation instead of a rewrite

The runtime stack review found no evidence that Python is the principal
bottleneck. FastAPI, PostgreSQL, Redis, SQLAlchemy, Alembic, Python workers,
Docker Compose, and bounded Next.js surfaces remain appropriate.

The initial observation showed no active queue backlog and all required hot
path indexes were present. Provider latency and error concentration were more
significant than local CPU or memory evidence. The current decision is
`keep_current_stack_observe`, not a Go/Rust rewrite or a new queue/workflow
platform.

Relevant records:

- `docs/runtime-stack-decision-history-2026-07-09.md`
- `docs/runtime-stability-performance-evidence-v1.md`
- `docs/runtime-stability-observation-2026-07-09.md`

## 4. Verified Closed Historical Debt

The following areas are considered closed unless a new migration contract is
explicitly approved:

- legacy site-key scope aliases are rejected;
- site grant without account membership is rejected for Portal access;
- retired task-pack APIs and product surfaces remain absent;
- retired Agent/Workflow registry names are not compatibility aliases;
- old hosted-model admin route aliases and redirects remain retired;
- provider credentials are managed through the active service/provider
  settings path rather than restored as documented production env surfaces;
- GitHub is the only release target;
- local WordPress remains the approval and final-write owner;
- Cloud metadata projection remains read-only detail rather than registry
  truth.

## 5. Historical Debt Closeout

The historical cleanup items below were closed on the follow-up release-candidate
branch with focused tests. Production promotion remains a separate operator gate.

### 5.1 Old configuration aliases

`app/core/config.py` now accepts only canonical `ADMIN_*` and `OPENAI_*` runtime
environment names. Retired `OPS_*` and `OPENAI_COMPATIBLE_*` runtime aliases are
ignored and covered by rejection tests.

Production `.env.deploy` must use only canonical names before promotion.

Provider import tooling may continue to recognize external provider formats
when explicitly used as an import command; that does not require the runtime
settings object to accept the same aliases forever.

### 5.2 Old QQ callback route

`app/domain/service_settings.py` accepts only:

```text
/open/auth/qq/callback
```

The second path is now retired and rejected. QQ Open Platform must use the
canonical `/open/auth/qq/callback` path.

### 5.3 Service-setting encryption fallback

Service-setting encryption now requires `NPCINK_CLOUD_SERVICE_SETTINGS_SECRET`
and no longer tries admin-session, Portal JWT, or internal-auth secrets.

The pre-removal migration was completed for local stored SMTP and Alipay
credentials. Before production promotion:

1. keep `NPCINK_CLOUD_SERVICE_SETTINGS_SECRET` stable on the production host;
2. exercise SMTP, QQ, and Alipay settings so readable legacy ciphertext is
   migrated;
3. restart the API and confirm all stored credentials remain readable;
4. verify no legacy-encrypted rows remain;
5. confirm the deployed build has no fallback decryption.

Do not rotate or remove the dedicated key as part of an application rollback.

### 5.4 Mypy debt exceptions

`scripts/check-changed-python-quality.sh` now runs targeted Mypy checks for:

- `app/domain/commercial/service.py`
- `app/domain/runtime/service.py`

Both files pass the targeted command and the explicit debt exceptions were removed.

### 5.5 Cleanup-only old cookies

Old `magick_*` admin, Portal, QQ nonce, and locale cookie cleanup branches were
removed after canonical PC login and Addon-binding browser tests passed.

Canonical login, logout, locale persistence, QQ state cleanup, and Addon return
behavior remain covered without the retired cookie names.

### 5.6 Internal legacy adapter seams

Some internal runtime/provider code still projects DB-managed provider
connections onto older `Settings` fields, and internal runtime models still
contain bounded legacy callback handling. Public runtime routes already disable
request-time legacy callback URLs.

These are implementation debt, not permission to restore public legacy
contracts. Refactor them only when the owning module is already being changed,
with tests proving public behavior remains fail-closed. Avoid a broad rewrite
that adds risk without reducing a user-visible or operational burden.

## 6. Current Release Snapshot

As of 2026-07-10:

- branch: `codex/cloud-admin-portal-commercial-polish`;
- PR: `#146`, targeting `master`;
- latest inspected commit before this document: `03f51097`;
- PR checks: frontend, backend static analysis, three backend pytest shards,
  CodeQL, secret scan, PR-body contract, and aggregate backend are green;
- merge state: mergeable but blocked, with no human review decision recorded;
- change size before this document: 90 files, 8,849 additions, 2,461 deletions.

The CI failure previously caused by support-mixin typing was fixed in
`2ed1e7e2`. Portal account-membership cleanup and explicit site-selection smoke
alignment were subsequently added in `9d4c1852` and `03f51097`.

The PR is mechanically green but large. It should not be treated as production
approval merely because CI passes. Review should explicitly cover commercial
currency behavior, account-scoped authorization, support request data handling,
service-setting secret migration, provider administration, and PC Admin/Portal
workflows.

Production promotion remains subject to
`docs/cloud-production-release-policy-v1.md` and the open gates in
`docs/pc-launch-readiness-2026-07-10.md`, including real mailbox/provider tests,
stable service-setting encryption, a database backup/restore command, known
rollback SHA, and the operator approval sentence.

## 7. Recommended Execution Order

Use the following order before formal public release:

1. review and merge PR `#146` into `master` only after its large cross-surface
   scope is understood;
2. run the production-readiness checks and record backup, rollback, SMTP, QQ,
   Alipay, and signed-site evidence;
3. done on the release-candidate branch: old `OPS_*` and runtime
   `OPENAI_COMPATIBLE_*` aliases are removed;
4. done: the old QQ callback path is rejected;
5. done in code and local data: old-key fallback is removed;
6. done: the two targeted-Mypy debt exceptions are removed;
7. done: cleanup-only old cookies are removed after browser-flow verification;
8. promote `master` to `production` through the documented release PR and
   monitor the timing summary, deploy smoke, runtime health, and rollback path.

Do not expand the effort into a language rewrite, a second workflow platform,
or generalized infrastructure modernization. The release objective is a small,
canonical, observable system with no accidental compatibility promises.

## 8. Definition of Done

Historical debt is considered closed for the first public release when:

- all accepted public API, auth, callback, and configuration names are
  canonical and tested;
- retired names are rejected rather than translated;
- any remaining migration reader has a named owner and deletion condition;
- the production database and `.env.deploy` no longer require old aliases or
  old encryption keys;
- no core module is excluded from the intended type-check gate;
- GitHub `master` and production-promotion CI are green;
- production smoke and operator-only external-account checks are recorded;
- rollback SHA, database backup, and restore procedure are known;
- Cloud remains runtime/detail only and local WordPress remains the final
  governance and write owner.
