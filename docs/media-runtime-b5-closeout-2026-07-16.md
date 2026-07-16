# Media Runtime B5 Closeout 2026-07-16

Status: pending evidence; P3-B5 is not complete.

## Purpose

P3-B5 is the bounded media closeout and release-validation batch after the
P3-B4D development integration proof. It determines whether the WordPress-first
media runtime can be reproduced from exact committed sources in a fresh
environment with measured performance, security, rollback, and cross-repository
evidence.

P3-B5 is not the global P5 refactor milestone. It does not authorize a
production deployment, does not authorize enabling production orphan cleanup,
and does not expand the current image contract to audio, video, documents, or
additional CMS adapters.

## Boundary Freeze

- Cloud remains the temporary media runtime and transfer-evidence owner only.
- WordPress remains the permission, review, approval, apply, rollback, and
  canonical local audit owner.
- Delivery ACK records verified transfer only and does not change the original
  artifact expiry.
- Exact packages must not restore compatibility aliases, download URLs, public
  tokens, Base64 media payloads, storage keys, or Cloud-side CMS write fields.
- `NPCINK_CLOUD_ARTIFACT_ORPHAN_CLEANUP_ENABLED` remains `false`; B5 proof is
  not cleanup enablement evidence.

## Definition Of Done

P3-B5 may be marked complete only when every row below is `passed` and links to
reproducible evidence. A prior B4D run, a green narrow test, or an unrecorded
manual observation cannot substitute for a missing row.

| Evidence | Required proof | Status | Recorded evidence |
| --- | --- | --- | --- |
| Exact package manifest | Record the Cloud commit and each of the five WordPress plugin commits, package filenames, SHA-256 checksums, build commands, and an exclusion check proving no source-only or secret material entered the packages. | pending | Awaiting exact-package build evidence. |
| Fresh environment E2E | Install the exact packages into a fresh WordPress environment, start Cloud from the recorded revision, then prove upload, job, signed pull, exact transfer ACK, local review/adoption, Core audit, HTTP visibility, restore, and fixture cleanup. | pending | Awaiting fresh-environment run, artifact, delivery, site, and environment identifiers. |
| Performance and bounded memory | Record representative input/output sizes, wall time, queue/processing time, and peak memory for upload, processing, and pull. Exercise the 50 MiB upload boundary, 25 MiB deliverable-output boundary, 8,192-axis limit, and 16,777,216-pixel limit with expected fail-closed outcomes. | pending | Awaiting measurement report and commands. |
| Security and isolation | Prove same-site success plus cross-site denial, nonce/idempotency replay handling, expiry/purge denial, checksum/size/MIME/decode failure, no arbitrary callback delivery, no credential-bearing result fields, and no CMS write authority from ACK. | pending | Awaiting focused test and fresh-environment evidence. |
| Upgrade, rollback, and recovery | Rehearse upgrade from the recorded pre-B5 baseline, WordPress local adoption rollback, database backup/restore, and ArtifactStore restoration or deterministic reset. Record failure injection and the verified recovery state. | pending | Awaiting rehearsal record. |
| No old media aliases | Prove the five plugins and Cloud active code accept only the current media upload/job/artifact/ACK contracts. Remove remaining Addon upload-input aliases and Toolbox preview-input aliases; record focused searches and tests. | pending | Awaiting deletion commits and zero-match evidence. |
| Central cross-repository matrix | Run the canonical matrix from `/Users/muze/gitee/npcink-workflow-toolbox` against the exact recorded commits and retain the complete result. | pending | Awaiting final matrix output. |
| Independent review | Review the staged cross-repository diff for boundary drift, exact-contract drift, secrets, unbounded buffering, skipped local governance, and cleanup enablement. | pending | Awaiting reviewer report. |

## Completion Rule

Do not change this document to `complete` until the exact evidence is attached
and independently reviewed. If any row fails, record the failure and keep the
status pending; do not weaken the gate, add a compatibility alias, or enable
production cleanup to make the run pass.
