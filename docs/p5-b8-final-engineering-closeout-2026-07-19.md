# P5-B8 Final Engineering Closeout — 2026-07-19

Status: historical P5-B8 code-owned/local engineering gates passed at the
recorded revisions. Later migration, test, documentation, and deployment work
is not covered by the recorded exact bundle and requires a new build, scan,
and replay. The P0-P5 architecture remains frozen, but global P5 and the
overall refactor phase-exit remain incomplete until the operator-only
P1-E05/P1-E06 evidence exists. This is not a production release, GA decision,
or real-user value claim.

## Decision

The broad system refactor should stop here. The accepted engineering shape is
still WordPress-first: one Cloud hosted runtime and one locally governed
WordPress integration, with only the minimal platform-neutral seams needed for
a later adapter experiment. Typecho, Z-BlogPHP, Ghost, and additional media
types stay post-P5.

Stopping is deliberate. The implementation has removed the known contract
ambiguity, bounded the Cloud/local ownership split, proved the WordPress text
and media contract/UI/write-boundary loops, and established repeatable release
and recovery gates. More architecture work before operator and real-provider
evidence would add more
surface than knowledge. The trade-off is that operator-only phase-exit proof
and several production questions remain open and block production promotion
and GA.

## Accepted Scope And Boundary

- Cloud owns hosted execution, provider routing, usage and entitlement
  evidence, health and diagnostics, temporary artifacts, and transfer evidence.
- WordPress/Core owns permissions, local capability and workflow truth, review,
  governed adoption, audit where the operation is Core-governed, and every CMS
  write.
- Signed pull and delivery ACK prove transfer only. They never authorize a CMS
  mutation.
- The text path is suggestion-only. Its native editor save is a locally
  reviewed WordPress write and is not claimed as a Core proposal/audit path.
- The media path returns a temporary artifact; Core governance and WordPress
  perform the one local adoption, reference repair, restore, and final audit.
- No compatibility alias, parallel contract version, second runtime, second
  registry, new workflow engine, or direct Cloud-to-CMS write path is accepted.

## Revision And Release-payload Lineage

| Item | Exact value | Interpretation |
| --- | --- | --- |
| Current Cloud implementation HEAD | `054ae3d81e7beb43523c12581f8764e80080855b` | Current engineering closeout revision before this documentation batch. |
| Last release-payload revision | `0663d95f765a8c49154aac0536e26cbb51029094` | The exact bundle is bound to this revision, not to `054ae3d8`. |
| Exact bundle SHA-256 | `592d1ce23334cddf4a09db0f147d6db48aa1c696980adc24630ed333660baa17` | Accepted `linux/arm64` bundle replayed without rebuild or pull. |

The changes from `0663d95f` through `054ae3d8` are limited to the B7 evidence
documents, Dependabot configuration, the release-policy checker, and its
contract tests. The original closeout treated those changes as outside the
release payload. Integration review corrected that conclusion: the Dockerfile
copies `scripts/**` into the API image, so the release-policy checker changes
the API build context even though application and frontend source are
unchanged. The `0663d95f` bundle remains valid historical evidence only for
that exact `linux/arm64` revision; it does not represent `054ae3d8` or any
later branch head. A current AMD64 release requires a fresh build, scan,
manifest, and same-bundle replay.

## Exact WordPress Acceptance Set

The disposable environment used WordPress `7.0.1`, official WordPress AI
`1.1.0`, and the five project plugins below. The offline five-plugin baseline
passed, the installed package trees matched the exact ZIP trees, and all six
plugins were active for text and media acceptance.

| Component | Exact source/package revision where applicable | ZIP SHA-256 |
| --- | --- | --- |
| WordPress core `7.0.1` | official release ZIP | `f171740cf45b1f5a1bf52194ca914787cd9d8ea078599b430eca951b62b2d000` |
| WordPress AI `1.1.0` | official release ZIP | `cec67bc85daa7b02a1444bc6ee808fcd151a6c7a249088ed6d16a4bee2335dcb` |
| `npcink-abilities-toolkit` | `d3d0b03a20a14d31b70fc52e77914e751669ccc6` | `cf07aca9d3a499d127380a3026d2492d3424b0210ddb1b13466b7958d38fe466` |
| `npcink-governance-core` | `71ba6be21d72622c40eb7a66a34281cc316b49c2` | `32d166641041069b3e031a97d2ce2505e8077566de30b16e4931281e54ab9acd` |
| `npcink-ai-client-adapter` | `e285f070f2f2ab9258da0bcf02f9a0bff653535d` | `21a079059db7238ecd4eceda9c610314c15ee74019b30a458d1aca36402a4156` |
| `npcink-workflow-toolbox` | `2c75273cb717eb3fc2214c42841ce84f269fa4b3` | `fe43a597c3bcce5ca5816d0d038f3cc232704fde55a3f60dde34846aca67114b` |
| `npcink-cloud-addon` | `044c05f73201c5540977a90e518b3dc8295f3dbe` | `1097890377ac2cc8c88dcc0f890c0b0e9b0a59952b99147aa5aec037ebc468a1` |

Toolkit, Core, and Adapter package cleanup removed only development/repository
material from their install ZIPs. It changed no runtime behavior and avoided a
package compatibility layer.

## P5-B8 Evidence Inventory

These are local engineering evidence locations, not durable production
storage. The hashes identify the exact accepted receipts; a missing local file
must not be reconstructed and presented as the original evidence.

| Evidence | Local path | SHA-256 |
| --- | --- | --- |
| WordPress offline baseline eight-file relative-path manifest | `/tmp/p5b8-evidence-20260719/wordpress-baseline/SHA256SUMS` | `412a3a3defb26b8050d8167eff32a0b97e78201b5a432192884d4aba53810173` |
| WordPress text evidence manifest | `/tmp/p5b8-evidence-20260719/text/SHA256SUMS` | `f489d845f75229573e10370075d3b896e400c82fb98895fae092767f3f4cb743` |
| WordPress media evidence manifest | `/tmp/p5b8-evidence-20260719/media/SHA256SUMS` | `e5f2dde0bb8c3b0a3a681fda0e1c6e387e723e2975be62099f06876780849b72` |
| Backup/restore result | `/tmp/p5b8-evidence-20260719/backup-restore-drill.json` | `a7479fe2dc4b4a8d6bd33a488bb84c60779f9acb8784d9d483c894e75e136a64` |
| Strict six-repository matrix | `/tmp/p5-b8-six-repo-matrix.json` | `110e40bfe2d5ca868e1e2fecf6f777fb60c822328c4a0af776b666a797e4a7e3` |
| Deterministic provider harness source | Historical path `/tmp/p5b8-deterministic-openai.py`; removed after accepted inspection and no longer locally re-verifiable | `fdb3ec8ceb5bddf06a7028865ab89fe95b91b4e8bbf7982940ea98757e04fb8b` |

## Final Test-resource Cleanup

Cleanup ran only after the final local gates. The exact B8 Cloud Compose
project's eight containers, three volumes, and network were removed. The
development test project's two containers, three volumes, and network were
also removed. Ports `18090`, `18120`, `18898`, `5433`, and `6380` had no
listeners afterward.

The deterministic-provider process and source file, extracted bundle root,
and disposable WordPress root were removed. The exact WordPress database and
its `localhost` test user both changed from one matching record to zero. The
shared Local MySQL service and socket remained online. Before deleting the
WordPress root, its eight redacted baseline files were copied to the evidence
directory; `8/8` entries in the retained `SHA256SUMS` verified successfully.
No global Docker prune, shared-service stop, image deletion, or unrelated
worktree cleanup was performed. Two exited review containers and their one
purpose-built artifact volume from the same P5 review were also removed by
exact name after an independent cleanup audit found them.

## Requirement-to-evidence Audit

The only status values in this audit are `passed`, `named temporary
exception`, and `production-only not claimed`. A `passed` row means the named
local engineering requirement passed; it does not upgrade a production-only
row. Material limitations and failed-first evidence are recorded separately
below rather than being disguised as a fourth status or as a clean first pass.

| Requirement | Current authoritative evidence | Status |
| --- | --- | --- |
| P0 target, ownership, future-CMS, and media contracts | [Master plan](refactor-master-plan-v1.md), [ADR-004](decisions/004-wordpress-first-cloud-runtime-refactor.md), [multi-platform boundary](multi-platform-connector-boundary-v1.md), and [media boundary](media-runtime-boundary-v1.md) freeze the destination and non-goals. | passed |
| P0 baseline and deletion ownership | [Refactor baseline](refactor-baseline-2026-07-14.md) records initial security/performance/structure measurements; [deletion inventory](refactor-deletion-inventory-v1.md) assigns every retired path to a phase. | passed |
| P0 executable contract and documentation gates | The final contract suite passed `340` tests with `31` intentional skips; target markers and referenced documents are present. | passed |
| P1 canonical site, connector, and object seam | [P5-B1](p5-b1-hosted-profile-contract-cutover-2026-07-17.md) and the connector boundary prove `site_url`, `platform_kind=wordpress`, connector metadata, generic object reference, `cloud_connector_runtime.v1`, and `wordpress_operation.v1`. | passed |
| P1 one active contract and no compatibility path | P5-B1 records an empty active-source search for the superseded combined connector version and former hosted-profile field; no alias, dual read/write, or version negotiation remains. | passed |
| P1 identity, durable-run ownership, and migration | `principal_id`, account, membership, site, and local actor remain separate; `run_records` stays Cloud-hosted truth and Redis non-canonical. Alembic head is `20260717_0068`, with SQLite and PostgreSQL semantic rehearsal recorded by P5-B1. | passed |
| P1-E05 production title execution | The current production connector runbook still marks this as operator-only phase-exit proof. P5-B8 deterministic WordPress evidence cannot close it, so it blocks production promotion and GA. | production-only not claimed |
| P1-E06 production-like inventory, carry-forward, and restore | The deletion inventory and production connector runbook still require operator evidence. The disposable restore drill cannot close it, so it blocks production promotion and GA. | production-only not claimed |
| P2 title, summary, and selected-text rewrite | P5-B8 records POSTs from all three editor endpoints and `6/6` successful Cloud runs, proving the recorded transport/UI path. [P5-B3](p5-b3-wordpress-ai-text-acceptance-2026-07-18.md) remains the task/profile and real-provider runtime-metadata evidence: `fb3c1d7..0663d95f` is empty for the connector, WordPress operation, provider-adapter, and runtime-route seams, while `0663d95f..054ae3d8` changes none of those source seams or frontend source. P5-B8 alone is not task-semantic routing proof, and the historical bundle is not current release evidence. | passed |
| P2 real Save-and-Verify connection path | The WordPress settings handler performed capability and nonce checks, stored an encrypted credential envelope without plaintext credentials, and ended configured, verified, and connector-enabled. | passed |
| P2 suggestion review and local write ownership | Pre-save WordPress writes were `0`; the user-visible review path then performed exactly `1` save with revision delta `+1`, preserved non-target sentinels, and removed the fixture. Cloud performed no WordPress write. | passed |
| P2 idempotent local apply and failure posture | The data-path proof records one explicit apply and a second no-op; [P5-B3](p5-b3-wordpress-ai-text-acceptance-2026-07-18.md) retains deterministic offline/failure and runtime-metadata evidence for the unchanged local package path. | passed |
| P3 artifact and transfer architecture | The media boundary and [P3-B5](media-runtime-b5-closeout-2026-07-16.md) record `MediaArtifact`, local-volume storage, streaming, typed operations, signed pull, delivery ACK, TTL/purge, and site isolation. | passed |
| P3 media byte and data policy | PostgreSQL blobs and run-record Base64 media bytes are removed; relational state contains metadata/evidence only, logs exclude media bytes, and artifacts are temporary and site-scoped. | passed |
| P3 exact WordPress browser preview | The media manifest records `32` assertions, bounded Core read authorization, artifact-descriptor-only response, same-origin nonce review, verified WebP bytes, revoked object URLs, and absent retired Adapter routes. | passed |
| P3 full media round trip and local governance | Upload/job, signed pull, `2/2` exact delivery evidence, ACK-without-TTL-change, Core governance, one local adoption, attachment/reference repair, WebP adoption, original PNG hash restoration, and cleanup passed. Cloud performed no CMS write. | passed |
| P3 bounded streaming memory and rejection limits | [P5-B4](p5-b4-runtime-load-soak-closeout-2026-07-19.md) records maximum-pixel RSS delta `340,189,184` bytes below the `402,653,184` budget, four over-limit probes rejected, five conversions accepted, and two unsupported cases rejected. | passed |
| P4 Portal/Admin contraction and authorization | [P4 inventory](p4-portal-admin-surface-inventory-2026-07-16.md) and ADRs 016, 018, and 019 retain bounded Cloud surfaces. Current API `889`, perimeter `9`, frontend, and anti-drift gates passed; unknown and cross-scope paths remain fail-closed. | passed |
| P5 deterministic runtime load/soak | P5-B4 records three fresh `29/29` baselines. Queue-wait p95 was `4.6318`, `5.0296`, and `4.7298` seconds; transport errors, HTTP 5xx, and terminal residue were zero. | passed |
| P5 high-cardinality query evidence | P5-B4 used `100,000` run records and `20,000` provider-call records; all six canonical queries passed and the highest p95 was `4.4282 ms`. | passed |
| P5 production worker scaling | The accepted topology used two proof-only workers while production defaults remain single-worker; concurrent-media and heartbeat ownership are not production-proved. | production-only not claimed |
| P5 production topology contraction | [P5-B6](p5-b6-production-topology-contraction-closeout-2026-07-19.md) removes bundled Caddy, Jaeger, and OTel Collector and fixes the external-Edge to loopback-NGINX to Gunicorn contract and rollback-aware migration. | passed |
| P5 exact release payload | [P5-B7](p5-b7-exact-release-bundle-closeout-2026-07-19.md) records five archives, eight roles, five scans, two same-bundle replays, migration, seed, health/live smoke, identity verification, and isolated cleanup for the exact bundle hash. | passed |
| P5 Python 3.14.6 image findings | Exactly `CVE-2026-11940`, `CVE-2026-11972`, and `CVE-2026-15308` are accepted by [the governed exception](p5-b7-python-api-image-cve-exception-2026-07-19.md), owner `Muze`, expiry `2026-08-05`, limited to `linux/arm64` engineering rehearsal. | named temporary exception |
| P5 disposable backup and restore | JSON SHA `a7479fe2dc4b4a8d6bd33a488bb84c60779f9acb8784d9d483c894e75e136a64` proves a synthetic representative graph on local Docker at head `20260717_0068`: database corruption and missing-artifact injections were rejected, fresh-restore database/artifact manifests matched, and every resource with the generated prefix was removed. It is not a B8 live-stack snapshot and does not satisfy P1-E06. | passed |
| P5 locked dependency review | Default and Zilliz locked Python audits report no known vulnerabilities; Pillow remains at the fixed floor established by [P5-B2](p5-b2-security-hardening-2026-07-17.md). | passed |
| P5 bounded dependency-update queues | Commit `054ae3d8` defines exactly `github-actions:/`, `npm:/`, and `uv:/`; each is weekly in `Asia/Shanghai`, staggered, labeled only `dependencies`, and limited to `2`. Docker stays in the digest-lock/image-scan lane. Canonical byte and semantic/adversarial tests include NUL rejection. | passed |
| P5 complete Cloud gate set | Contract `340 passed, 31 skipped`; domain `611 passed, 3 skipped`; API `889 passed`; perimeter `9 passed`; anti-drift passed; Ruff and mypy for `232` source files passed; frontend type-check, lint, contracts, and `33` unit tests passed; release policy passed. | passed |
| P5 exact packages and five-plugin gates | Offline baseline, exact installed-tree comparisons, package checks, and every WordPress repository `composer test:all` gate passed on the recorded revisions. | passed |
| P5 strict six-repository matrix | Matrix SHA `110e40bfe2d5ca868e1e2fecf6f777fb60c822328c4a0af776b666a797e4a7e3` reports `6/6` gates passed and worktree dirty/ahead/behind all `0`. Its separate stash caveat is retained below. | passed |
| P5 engineering rollback and cleanup | Whole-batch rollback rules, Edge rollback, exact bundle replay/cleanup, disposable database-plus-ArtifactStore recovery, and WordPress fixture/permalink restoration are recorded. | passed |
| Breaking/data policy | Replacements were atomic and obsolete aliases/routes/fixtures deleted. Secret-bearing state remained protected; media bytes stay outside PostgreSQL/run payloads; no compatibility layer was added. | passed |
| `LOCAL_CONTROL_PLANE` and no direct Cloud write | Text recorded zero pre-save writes and one local save; media recorded Core governance and one local adoption. Cloud retained execution/artifact/transfer evidence only. | passed |
| `WORDPRESS_FIRST` and `PLATFORM_CHANNEL_ORTHOGONAL` | P0-P5 accepted only WordPress. CMS platform and access channel remain separate, with no Typecho/Z-BlogPHP/Ghost implementation or platform-by-channel variant. | passed |
| Local/offline/privacy seam | The local contract retains fail-closed/governed fallback ownership and P5-B3 records the deterministic offline posture; Cloud does not become fallback truth. | passed |

## Material Limitations And Failed-first Evidence

- Deterministic provider harness source SHA-256 is
  `fdb3ec8ceb5bddf06a7028865ab89fe95b91b4e8bbf7982940ea98757e04fb8b`.
  The source was inspected before cleanup and then removed; only its historical
  receipt remains, so the source itself is no longer locally re-verifiable.
  Its broad marker classifier sent all three B8 requests through the rewrite
  branch. Title, summary, and rewrite therefore shared UI output SHA-256
  `c0af6e5469c8cd13008d9a5b8e84ac80c45bbcb89ff30594c1abe108a1f18f98`.
  B8 proves the three endpoint POSTs, transport, UI review, zero pre-save
  writes, and one explicit save; it does not prove task-specific semantic
  routing or editorial/model quality. P5-B3 remains the task/profile and real-
  provider runtime-metadata evidence.
- The first media browser run completed the product requests but failed the
  harness URL-owner pathname assertion because fresh WordPress used query-form
  REST routing with plain permalinks. The final harness pass used a temporary
  index permalink, after which the original plain permalink was restored. The
  first failure remains part of the record.
- Restore receipt SHA-256
  `a7479fe2dc4b4a8d6bd33a488bb84c60779f9acb8784d9d483c894e75e136a64`
  covers a synthetic representative graph in local Docker. Both failure
  injections were rejected and fresh-restore manifests matched, but the source
  archives, restored resources, and generated resource prefix were destroyed;
  only the summary was retained. It is not a B8 live-stack snapshot,
  persistent/off-host backup, production carry-forward, or RPO/RTO proof.
- The matrix reports Cloud `stash_count=1`: a pre-existing WIP stash dated
  `2026-06-29` for `service-settings-import-workflow`. It was not applied or
  modified and did not change the tested HEAD or worktree. Therefore the
  accurate claim is worktree dirty/ahead/behind `0`, not that every Git metadata
  surface was empty.
- External object storage remains an explicit deferred/non-goal. Its absence of
  evidence is not a production blocker for the accepted local-volume design and
  must not be converted into an implied requirement without measured need.

## Strict Matrix Revisions

The final matrix ran from the Toolbox-owned entry point. All reported worktree
`dirty`, `ahead`, and `behind` counts were `0`. Cloud also reported
`stash_count=1` and four linked worktrees; the material limitation above is
part of the accepted receipt.

| Repository | Full revision | Gate |
| --- | --- | --- |
| `npcink-abilities-toolkit` | `d3d0b03a20a14d31b70fc52e77914e751669ccc6` | `composer test:all` |
| `npcink-governance-core` | `71ba6be21d72622c40eb7a66a34281cc316b49c2` | `composer test:all` |
| `npcink-ai-client-adapter` | `e285f070f2f2ab9258da0bcf02f9a0bff653535d` | `composer test:all` |
| `npcink-workflow-toolbox` | `2c75273cb717eb3fc2214c42841ce84f269fa4b3` | `composer test:all` |
| `npcink-cloud-addon` | `044c05f73201c5540977a90e518b3dc8295f3dbe` | `composer test:all` |
| `npcink-ai-cloud` | `054ae3d81e7beb43523c12581f8764e80080855b` | matrix `npm run check:fast`; remaining Cloud gates ran separately |

## Production-only Claims Deliberately Withheld

| Requirement | Why local evidence cannot close it | Status |
| --- | --- | --- |
| P1-E05 and P1-E06 | The production connector runbook and deletion inventory require operator execution; both block production promotion and GA. | production-only not claimed |
| `linux/amd64` release artifact | The accepted exact bundle and image scans are `linux/arm64` only. | production-only not claimed |
| Production Edge, DNS, WAF, TLS, and OTLP | Contracts passed locally, but no operator-owned external infrastructure was configured or observed. | production-only not claimed |
| Production secrets and live credentials | No production secret, provider key, runtime-data key, or customer credential was read, rotated, or validated. | production-only not claimed |
| Production backup, carry-forward, RPO/RTO, and off-host durability | The restore evidence is a disposable synthetic local drill, not a B8 live-stack snapshot, persistent/off-host backup, or operational timing and retention commitment. | production-only not claimed |
| Independent penetration test | Automated security, perimeter, secret, dependency, and image gates are not an external penetration assessment. | production-only not claimed |
| Live provider quality, availability, latency, and cost | P5-B8 used a deterministic proof provider. No paid/live provider acceptance was performed. | production-only not claimed |
| Real-user usefulness and editorial/media value | There are no real users; contract correctness and local UI evidence do not prove usefulness, retention, or willingness to pay. | production-only not claimed |
| Production deployment, GA, or promotion | No production branch promotion, deploy, DNS change, external trial, or GA approval occurred. | production-only not claimed |

## Rollback And Evidence Expiry

- Roll back a failed integration as one code/schema/consumer/test/document
  batch; do not restore a compatibility shim.
- A production attempt must use the matched prior bundle, database backup, and
  secret/key recovery point described by the release policy and runbooks.
- A runtime/dependency/payload change invalidates the `0663d95f` bundle proof.
  A WordPress package change invalidates the matching ZIP and E2E evidence.
- The three-CVE engineering exception expires on `2026-08-05`. A later scan
  must show the findings removed or obtain a new explicit decision.
- Any failed operator-only or production gate stops promotion. Local
  engineering acceptance cannot override it.

## Next Stage

The next stage is not another broad refactor.

1. Freeze the P0-P5 architecture and complete P1-E05/P1-E06 plus production
   operator readiness: intended topology, secret/config inventory, rollback,
   external Edge/TLS/DNS/WAF/OTLP, `linux/amd64`, and production-shaped backup
   evidence under separate authorization.
2. Run a small real-provider editorial and media trial through the same
   WordPress review paths. Measure task-specific usefulness, failure rate,
   latency, cost, and operator burden; do not add automatic apply or publish.
3. Resolve or renew the three-CVE exception before expiry and rebuild the exact
   release payload for any changed source or dependency.
4. Only after those results are understood, decide whether a thin Typecho
   suggestion-only PoC for title, summary, and selected-text rewrite is worth
   doing. It must reuse the unchanged Cloud main path. Z-BlogPHP and Ghost stay
   deferred until that seam is proven.

This sequence converts remaining uncertainty into product and operator
evidence without making the current project more complex for hypothetical
platforms.

## Integration Correction — 2026-07-20

This append-only correction records later integration work. It does not alter
the revisions, hashes, pass counts, limitations, or production claims recorded
above.

- The ordinary deploy path now keeps every `.env.deploy` outside the release
  payload at `${REMOTE_DIR}/.release-state/<release-name>/env.deploy`, enforces
  `0700` state directories and a `0600` env file, and rejects an old/new Compose
  project mismatch before mutation.
- The cutover order is now fixed as exact-image preparation, old application and
  writer stop, data services, staged one-off migration/provider refresh with
  `--pull never`, atomic pointer update, API readiness, worker cutoff/container/
  heartbeat stability, generic operational readiness, and traffic restoration.
- After migration starts, failure remains fail-closed and never auto-starts the
  old application. If stopped-service, restored-pointer, or failure-marker proof
  is incomplete, the deployment lock remains for operator recovery. Success
  retains the matched per-release env state while removing the temporary
  rollback-image map and tags.
- These deployment, migration, test, and documentation changes are outside the
  historical `0663d95f` payload. That bundle remains only `linux/arm64` evidence
  for its exact revision; it is not evidence for current source,
  `linux/amd64`, merged `master`, or production.
- The next artifact must be rebuilt from the final merged `master` revision for
  `linux/amd64`, scanned with the governed release policy, manifested, and
  replayed twice from the same bundle before production validation. Until then,
  the production-only claims above remain withheld.
