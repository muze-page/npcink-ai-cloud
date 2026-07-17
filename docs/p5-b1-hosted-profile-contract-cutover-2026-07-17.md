# P5-B1 Hosted Profile Contract Cutover

Status: engineering batch complete; global P5 release closure and production
approval remain incomplete.

Date: 2026-07-17.

## Outcome

Hosted Runtime Profiles now bind the platform-specific
`wordpress_operation.v1` contract through
`operation_contract_version`. The public execution path remains the single
platform-neutral `cloud_connector_runtime.v1` envelope, while the Admin
resource remains `cloud-hosted-runtime-profiles.v1`.

This is a direct cutover. Active backend, frontend, fixtures, and tests contain
no superseded combined connector version or former hosted-profile identity
field. There is no alias, fallback, dual read, dual write, or version
negotiation path.

`connector_id=wordpress_ai_connector` is the hosted-profile namespace. It is
not the deployed runtime-envelope connector implementation identifier. The
distinction prevents a future CMS adapter from becoming another Cloud runtime
or from being confused with an editor/API/MCP/OpenClaw access channel.

## Scope

Changed together:

- Admin GET/PUT types, projections, audit payload, and strict request
  validation;
- catalog defaults and managed runtime-policy validation/projection;
- frontend types, fail-closed response validation, PUT payload, UI copy, unit
  contracts, and Playwright coverage;
- current boundary documentation and ADR rollback semantics;
- Alembic `20260717_0068`, which converts only current hosted-profile policy
  JSON in `routing_profiles.default_policy_json` and
  `routing_bindings.selection_policy_json`.

The migration preserves candidate chains, operator notes, revisions,
timestamps, and unrelated policy fields. Historical run records and service
audit events are intentionally immutable and are not rewritten.

Not changed:

- WordPress ability, workflow, prompt, permission, review, approval, preflight,
  audit, or write truth;
- the public connector envelope or WordPress operation request/result shape;
- provider, queue, entitlement, usage, artifact, or media ownership;
- Typecho, Z-BlogPHP, Ghost, or any other future CMS implementation;
- production application state.

## Cross-repository Consumer Check

The five WordPress-side repositories were checked read-only before the Cloud
cutover. None consumes the retired Admin field or superseded version. Only the
Cloud Addon consumes the runtime contract, and it already uses the current
outer `cloud_connector_runtime.v1` plus inner `wordpress_operation.v1` pair.

| Repository | Revision | Result |
| --- | --- | --- |
| `npcink-abilities-toolkit` | `77321e8b4f7502bb454b8ddbfbf14b46961619e9` | clean; no consumer |
| `npcink-governance-core` | `af0e5128decb053bf0fa7a4e6448460e14d3f484` | clean; no consumer |
| `npcink-ai-client-adapter` | `60b90fa71ce5270cc896624b1d8701cceec81a8d` | clean; no consumer |
| `npcink-workflow-toolbox` | `2c75273cb717eb3fc2214c42841ce84f269fa4b3` | clean; no consumer |
| `npcink-cloud-addon` | `b74d4c3c4a7800fa82e2f9c2b85334660df750c6` | clean; current two-layer runtime consumer |

No WordPress repository change was required.

## Verification Evidence

| Gate | Result |
| --- | --- |
| Pre-change focused characterization | `297 passed` |
| Final focused Python/API/domain/contract/migration suite | `302 passed` |
| Frontend static dialog and i18n contracts | passed |
| Frontend TypeScript type-check | passed |
| Runtime Profiles Playwright spec | `7 passed` |
| Active source superseded-version/former-field search | empty across `app`, `tests`, `frontend/src`, and `frontend/tests` |
| Alembic head | `20260717_0068` |
| SQLite migration upgrade/downgrade/idempotency/atomicity | `4 passed` |
| PostgreSQL 16 semantic rehearsal | `0067 -> 0068 -> 0067` passed; both policy columns and preserved fields verified |
| `pnpm run check:fast` | contract `156 passed, 1 skipped`; domain `602 passed, 3 skipped` |
| `pnpm run check:seam` | API `746 passed`; perimeter `9 passed` |
| `pnpm run check:anti-drift` | passed |
| `pnpm run lint` | Ruff passed; mypy passed for `229` source files |
| `composer quality:matrix` | six repositories detected; five WordPress-side repositories clean; gates intentionally `not_run` in the status-only command |

The first PostgreSQL rehearsal used a JSON text-format equality assertion and
reported a false negative after the migration itself succeeded. The temporary
database was removed. The rehearsal was rerun with database-level semantic
boolean assertions and passed upgrade and downgrade; its second temporary
database was also confirmed removed. This distinction is retained so the
evidence does not hide a failed verification attempt.

Existing warnings were limited to the repository's pnpm override-location
warning, Starlette TestClient deprecation warning, and one pre-existing
Pydantic alias warning. No new warning was attributed to this batch.

## Review Resolution

Three cross-area read-only reviews found one release-blocking documentation
error: ADR-018 still described a code-only rollback despite the new data
migration. The ADR now requires coordinated application and migration order.
A second stale future-tense description in the multi-platform boundary was
also corrected. Both fixes were rechecked; no P0-P2 finding remains.

## Promotion And Rollback

Do not run mixed versions. Promotion requires stopping API and workers,
capturing the P1-E06 inventory/backup evidence, applying migration 0068, and
then starting the new application revision. Rollback requires stopping the new
application, downgrading 0068 or restoring the verified pre-migration backup,
and only then starting the previous revision.

This engineering rehearsal does not satisfy production approval, real
configuration inventory/backup/restore evidence, or the production title
execution proof.

## Remaining Work

- P1-E05 production title execution remains operator-only pending.
- P1-E06 production-like configuration inventory, backup, and restore remains
  operator-only pending.
- P2 current WordPress title/summary/selected-text review-and-apply evidence is
  still incomplete.
- P5-B2 security work, P5-B3 WordPress text acceptance, P5-B4 load/soak
  evidence, and P5-B5 release closure remain open.
- The full `composer quality:matrix:run -- --fail-on-dirty` gate remains a
  P5-B5 closeout requirement; the status-only matrix above is not a substitute.

This document closes P5-B1 only. It must not be cited as global P5 completion
or as approval for production validation.
