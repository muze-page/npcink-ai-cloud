# WordPress Media Product Acceptance 2026-07-16

Status: complete; local product acceptance passed. This does not authorize a
production deployment or production orphan cleanup.

## Purpose

This batch turns the completed P3-B5 media runtime contract into a bounded,
WordPress-first operator acceptance loop. It validates the real Toolbox
working surface, a representative image corpus, and a production-like local
deployment rehearsal without changing ownership or enabling production
cleanup.

This batch is not P4 Portal/Admin contraction. It does not start another CMS
adapter, add a Cloud media library, authorize production deployment, or expand
the current image processor to audio, video, documents, or arbitrary media
operations.

## Change Envelope

Target repositories:

- `npcink-workflow-toolbox`: operator progress, failure, preview, review, and
  governed handoff presentation for `media_optimization_v1`.
- `npcink-ai-cloud`: representative media proof and an explicit non-production
  staging-rehearsal entrypoint built from existing gates.

Explicit non-goals:

- no public REST or runtime contract change;
- no changes to Toolkit, Core, Adapter, or Cloud Addon ownership;
- no direct or automatic WordPress media write from Toolbox or Cloud;
- no automatic approval, execution, retry worker, queue, scheduler, or local
  run truth in Toolbox;
- no compatibility aliases or acceptance of retired media fields;
- no production SSH deployment and no secret or production environment
  mutation;
- no enablement of `NPCINK_CLOUD_ARTIFACT_ORPHAN_CLEANUP_ENABLED`.

Rollback is repository-local: the Toolbox UI commit, Cloud corpus proof commit,
and Cloud rehearsal commit are independently revertible. Existing P3-B5
runtime, transfer, ACK, review, adoption, restore, and audit contracts remain
valid if this acceptance batch is reverted.

## Ownership Freeze

- Cloud owns processing, temporary artifact bytes, run/usage/expiry/purge
  detail, and transfer evidence.
- Toolbox owns the WordPress operator working surface and suggestion/review
  presentation only.
- Cloud Addon owns signed transport and verified receive/ACK projection.
- Core owns proposals, approval, preflight, and canonical governance audit.
- Toolkit/Adapter/WordPress own the approved local apply, reference repair,
  rollback, and final CMS truth.

## Acceptance Matrix

| Evidence | Required outcome | Status |
| --- | --- | --- |
| Toolbox working surface | Progress states are explicit; errors give a bounded operator retry action; the result shows exact local review evidence; Core handoff remains separate from apply/rollback truth. | passed |
| Browser contract | The real WordPress administrator path uses only current media fields, performs same-origin no-store local review, and creates no direct media write. | passed |
| Representative corpus | Deterministic JPEG, PNG alpha, WebP, EXIF orientation, and unsupported animated input cover current processor behavior with bounded timing and memory evidence. | passed |
| Staging rehearsal | A non-production entrypoint reuses exact-bundle, recovery/isolation, release-policy, and cleanup-default-off gates without SSH, secrets, or copied runtime truth. | passed |
| Focused repository gates | Toolbox and Cloud focused suites, syntax/lint gates, and changed-file contracts pass. | passed |
| Cross-repository matrix | The canonical six-repository gate passes from the final clean commits. | passed |
| Independent review | Correctness, security, performance, UX hierarchy, and Cloud/WordPress ownership review has no open blocker. | passed |

## Executed Evidence

- The Toolbox browser smoke drove the real administrator workbench. It created
  a bounded one-time read request through Adapter, required an explicit
  operator click recorded by Core, and ran the Toolkit batch planner with the
  exact `read_request_id`. No candidate was returned before that authorization.
- The same smoke forced a polling timeout, exposed one explicit continue
  action, and then read the original Cloud run without a second upload or run
  creation. The Core submit action stayed disabled until the exact same-origin
  local-review POST returned image bytes and the browser completed `onload`.
- The browser verified the current `preferred_format`, `target_max_width`,
  crop, and watermark request fields, queryless no-store review transport,
  WordPress REST nonce handling, and object URL revocation. It observed no
  retired Adapter media facade and no WordPress media write.
- `pnpm run check:media:corpus` passed five transforms plus two fail-closed
  rejects. The large deterministic case reduced a roughly 15.94 MiB 2304 x
  2304 PNG to a roughly 1.50 MiB 1600 x 1600 WebP in about 0.51 seconds, with
  about 21.2 MiB measured RSS growth. The suite also proved exact resized alpha,
  EXIF orientation pixels, input ICC/EXIF/GPS presence, output metadata
  stripping, checksum verification, and no network, persistence, or CMS write.
- `pnpm run check:media:staging` returned
  `MEDIA_RUNTIME_STAGING_REHEARSAL PASS target=local-staging mode=full passed=4 skipped=0`.
  It passed release policy, anti-drift, a fresh exact deploy-bundle replay, and
  `P3-B4C3` isolated artifact recovery. The entrypoint rejects inherited
  Compose/Docker/base-URL control variables, delegates through an allowlisted
  empty environment, requires an explicit disposable-local-Docker confirmation,
  forces `environment=test`, and keeps orphan cleanup disabled.
- Toolbox `composer test:all`, syntax, translation, package, and real-browser
  gates passed. Cloud focused contracts, Ruff, mypy, `check:fast`, `check:seam`,
  and `check:perimeter` passed. The canonical six-repository matrix passed from
  the final clean commits.
- Three independent reviews closed all earlier Critical/Important findings for
  the corpus, staging rehearsal, and Toolbox UI. The final reviews reported no
  open Critical, Important, or Suggestion item.

## Completion Rule

Every row above is backed by an executed local gate. A successful local
rehearsal does not authorize production deployment or production orphan
cleanup.
