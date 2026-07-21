# Media Runtime B5 Closeout 2026-07-16

Status: complete; all eight P3-B5 evidence gates passed on 2026-07-16.

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
| Exact package manifest | Record the Cloud commit and each of the five WordPress plugin commits, package filenames, SHA-256 checksums, build commands, and an exclusion check proving no source-only or secret material entered the packages. | passed | Cloud `7e90782275683efd9bdaf6a33b552528a79a3cba`; release-validation commits `0aa07c02563a4c73ca01d9ad22f77c9a47488ef3`, `d07c9bdaf4bece8c8f891fe07a2eb04da92c8781`, `5d3dfac0be64ebcd9ed70794a3b1fdd9d7797592`, and `7e90782275683efd9bdaf6a33b552528a79a3cba`. Final deploy bundle SHA-256: `77d7a0f8653119b9e17b2d4000f373af982e13476e620e213170b16473168927`. The exact plugin manifest is recorded below; ZIP integrity, one-root layout, and development/secret exclusions passed. |
| Fresh environment E2E | Install the exact packages into a fresh WordPress environment, start Cloud from the recorded revision, then prove upload, job, signed pull, exact transfer ACK, local review/adoption, Core audit, HTTP visibility, restore, and fixture cleanup. | passed | Fresh WordPress 7.0.1/PHP 8.2.29 run `run_914ca00b26964351b8d764c2b7254f9c`, artifact `art_402f108aa0a449c1a2966529a7944fb5`, and receive delivery `mdl_193e3d0fc5574481873494a72e3343ce` passed upload, receive, ACK, Core audit, HTTP/reference verification, restore, and cleanup. Post-upgrade watermark run `run_4ea4878039b84ca78860b438e4c077f5`, artifact `art_9b628d9c0e8a4dd38aab4e9429c9abae`, and delivery `mdl_cc8040d3cc3a46c69270f1c52ddf0036` also passed. |
| Performance and bounded memory | Record representative input/output sizes, wall time, queue/processing time, and peak memory for upload, processing, and pull. Exercise the 50 MiB upload boundary, 25 MiB deliverable-output boundary, 8,192-axis limit, and 16,777,216-pixel limit with expected fail-closed outcomes. | passed | Fresh E2E measured 12/11/25 ms queue/process/total, 3,493 to 1,384 bytes, and 800x450 to 320x180 WebP. Linux proof used 64 KiB streaming chunks: 50 MiB store 47.353 ms and pull 22.191 ms with 4,096-byte RSS deltas; 4,096-square processing took 1,808.328 ms with RSS delta 340,189,184 bytes below the 402,653,184-byte gate. 50 MiB + 1 upload, over-25 MiB output, 8,193-axis, and over-16,777,216-pixel cases all failed closed. |
| Security and isolation | Prove same-site success plus cross-site denial, nonce/idempotency replay handling, expiry/purge denial, checksum/size/MIME/decode failure, no arbitrary callback delivery, no credential-bearing result fields, and no CMS write authority from ACK. | passed | The 42-test media release proof and 13 focused security tests passed. Cloud fast, seam (710 + 9 tests), perimeter, anti-drift, Ruff, and mypy gates passed. The final exact proxy-trust chain and deploy smoke passed. Commit `7e90782275683efd9bdaf6a33b552528a79a3cba` removed `database_url` and `secret_hash` from seed CLI output; its focused test and Ruff passed. The bundle built from that commit passed remote replay, migration, redacted seed, and health smoke. ACK remains transfer-only with unchanged original expiry, and production orphan cleanup remained false. |
| Upgrade, rollback, and recovery | Rehearse upgrade from the recorded pre-B5 baseline, WordPress local adoption rollback, database backup/restore, and ArtifactStore restoration or deterministic reset. Record failure injection and the verified recovery state. | passed | Upgrade from Addon `f83d7e0` and Toolbox `5e97d54` to the final ZIPs remained active. The post-upgrade watermark/Core restore flow and local adoption rollback passed. PostgreSQL dump/restore retained migration head `20260716_0066` and equal source/restored counts of 883 runs, 45 artifacts, and 24 deliveries. Artifact isolation reported `PASS phase=complete`. |
| No old media aliases | Prove the five plugins and Cloud active code accept only the current media upload/job/artifact/ACK contracts. Remove remaining Addon upload-input aliases and Toolbox preview-input aliases; record focused searches and tests. | passed | Addon and Toolbox `test:all` passed. Old media names remain only in explicit rejection lists, not accepted input paths. Nested unknown fields and invalid image selectors fail closed. No compatibility consumer, download credential, binary persistence alias, or cleanup enablement remains. |
| Central cross-repository matrix | Run the canonical matrix from `/Users/muze/gitee/npcink-workflow-toolbox` against the exact recorded commits and retain the complete result. | passed | The final central `composer quality:matrix:run` completed at `2026-07-16T11:21:54Z` against Cloud closeout commit `831063b9b9d646490df44cac639c3296d293bf89`: all six repositories passed with `dirty=0`; Cloud `npm run check:fast` passed in 233,242.8 ms. This follow-up changes evidence text only and was checked with the focused closeout contract after the matrix. |
| Independent review | Review the staged cross-repository diff for boundary drift, exact-contract drift, secrets, unbounded buffering, skipped local governance, and cleanup enablement. | passed | One independent reviewer found no boundary or contract blockers. A second review found an RFC1918 `X-Real-IP` trust weakness; commit `5d3dfac0be64ebcd9ed70794a3b1fdd9d7797592` replaced it with the exact Caddy `172.28.0.11` to Nginx `172.28.0.10` to Gunicorn chain. Its re-review closed the finding after 13 proxy contract tests passed, one environment-dependent case skipped, and release-policy validation passed. The final deploy-bundle smoke then exposed seed CLI disclosure of `database_url` and `secret_hash`; root review fixed both in `7e90782275683efd9bdaf6a33b552528a79a3cba`. Its focused test and Ruff passed, and the rebuilt bundle passed remote replay, migration, redacted seed, and health smoke. No ownership, ACK/TTL, secret, local-governance, or cleanup-enable drift remained. |

## Exact Package Manifest

| Component | Commit | Package | SHA-256 | Build entry |
| --- | --- | --- | --- | --- |
| Abilities Toolkit | `f17d7a67077dd674e2ca9f4a043fa9117a423291` | `dist/npcink-abilities-toolkit-0.5.3.zip` | `0c921a6ea05de2326e5c3872dce00191b29eb59e98f9d96484bd69e8b0814ca6` | `composer release:zip` |
| AI Client Adapter | `c819e7a6b7b35497cc3f215aaf96739390cb9afb` | `build/npcink-ai-client-adapter.zip` | `8c6cc2b32655a2380ecb9ec91827bda21ab4419b293d12c49fcfdc5652f3ab8b` | `composer package:release` |
| Governance Core | `6bd67f30f35516e7c37818dd427935b00ab513f2` | `build/npcink-governance-core.zip` | `c681249bbb8d5a05006b35a12dbae6f09b12eed9ac3e645b6f8ecc4f1889f4f1` | `composer package:release` |
| Cloud Addon | `026ee88ece4048d2c98cae13798667da8eeec091` | `build/npcink-cloud-addon.zip` | `ce0656cca9624c58b64f2ac75d662d1a6cdfd8b1a69b08fe8cf4acc8d460e8c9` | `composer package:release` |
| Workflow Toolbox | `4ef40ecd57bc79a335d47c57c482a6c5e4d2d779` | `build/npcink-workflow-toolbox.zip` | `012445852b2306eac8f3471c2ef17cabe69238e4db86a43cf48caddd311ecd21` | `composer package:release` |
| Cloud deploy bundle | `7e90782275683efd9bdaf6a33b552528a79a3cba` | `dist/deploy-bundle.tgz` | `77d7a0f8653119b9e17b2d4000f373af982e13476e620e213170b16473168927` | `pnpm run bundle` |

## Completion Rule

All eight gates passed and P3-B5 is complete. This completion closes the
bounded WordPress-first media release-validation batch only. It does not mark
the global P5 refactor complete, authorize production deployment, or authorize
enabling production orphan cleanup. Any later change to the exact packages,
media contracts, proxy trust chain, storage backend, CMS ownership, or cleanup
configuration requires new evidence rather than inheriting this result.
