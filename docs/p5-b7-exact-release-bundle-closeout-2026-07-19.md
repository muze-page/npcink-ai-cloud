# P5-B7 Exact Release Bundle Closeout — 2026-07-19

Status: **engineering acceptance complete** for Cloud revision
`0663d95f765a8c49154aac0536e26cbb51029094` on `linux/arm64`.
P5-B8 WordPress text/media replay, backup/restore rehearsal, final Cloud and
five-plugin gates, the strict six-repository matrix, dependency follow-up, and
the final P0-P5 audit remain incomplete. No production or GA action is
authorized by this result.

## Accepted Outcome

P5-B7 produced one clean-tree, exact release bundle and replayed that same
archive twice without rebuilding or pulling during deployment:

| Field | Accepted value |
| --- | --- |
| source revision | `0663d95f765a8c49154aac0536e26cbb51029094` |
| source tree | `dfefcda4751a74418435c01e2479935fd5d242bf` |
| branch | `codex/p5-b5-release-closure` |
| bundle creation | `2026-07-19T15:05:27+00:00` |
| build/scan platform | `linux/arm64` |
| Docker context / builder | `desktop-linux` / `desktop-linux` |
| Docker daemon | `linux/aarch64`, the daemon spelling for native arm64 |
| bundle path | ignored local artifact `dist/deploy-bundle.tgz` |
| bundle bytes | `302834143` |
| bundle SHA-256 | `592d1ce23334cddf4a09db0f147d6db48aa1c696980adc24630ed333660baa17` |
| checksum-file SHA-256 | `4b1aef59a0ceb42e003908ca43af39bfbfc359095a07183914e5392359c6f3ab` |
| manifest schema | `npcink.release-bundle.v1` |
| manifest SHA-256 | `c5f82b97f2955a9ea83828cf823d789a4582a66b173565a0d5e20e72d7e96343` |
| payload records | `95` |
| internal `SHA256SUMS` | `96` records covering the manifest and all payloads; SHA-256 `754a92293f99813d43249af4fa839f4612ee43e9683380ed6126205c4b723939` |
| image archives / roles | `5` / `8` |
| scan evidence files | `27` |
| scan index SHA-256 | `35bae9c632ccbef891c1914ffd224e0d33aa2a289fbe9582e81f919af75a7108` |

The 96 internal checksum records cover the manifest and all 95 payloads; the
checksum table does not self-cover. The manifest and checksum table cover the
final compressed image archives, while the image table below records the
scanner's uncompressed `image.tar` inputs.

The five archives are `api`, `frontend`, `postgres`, locked external Redis,
and locked external NGINX. API is the one scanned and archived image for the
`api`, `worker`, `callback_worker`, and `ops_worker` roles, so the manifest has
eight roles but only five physical image archives and five portable Config
IDs.

## Image Supply Evidence

The canonical image lock SHA-256 is
`97136387a406b297ba020e9a6c7019667ac72d9ab3dc668aa56fed7e12c9f008`;
the governed CVE allowlist SHA-256 is
`37c75c3a04d2996182b41e75c653045526862b24f599385c1a26c716c1e32875`.
The lock contains seven production inputs, six application outputs, and two
scanner images. The release scan covers exactly five subjects.

Syft `1.33.0` and Grype `0.98.0` were digest locked. The shared Grype database
was schema `v6.1.9`, built `2026-07-19T07:00:56Z`, valid at scan time, and had
SHA-256 `d0b377f7c0e72a3ccc1f3418d91877154229df26720e284cefd74d27633f96ea`.

| key | source / archive identity | source ID / portable Config ID | scanner image.tar / SBOM / Grype / receipt SHA-256 | allowed / unallowed blocking |
| --- | --- | --- | --- | --- |
| `api` | `npcink-ai-cloud-api:prod` | `sha256:408400a08d31616a92b0466c8eda39ea3ce51ba793fef3266ea601222d236a58` / `sha256:4e7959bbaa84319b3a436ae446adbe05e3fc588d49dbf76f62e9b85afcd2ea30` | `d64fb7c776bc869c51f2c2265b3e40e828df5aaf51911b137d6a4830e55b9850` / `eafcfa8952215cf0144210664f60d42dca1d91d1a4658100fd0d5d0f3bbea127` / `feb11d67a5ba7b60f16c37c3cfae6bf41ca78a4cd4adb5fe1c9d786f7ac458af` / `45610422c4b29fd02b86b5238ac40c7bb3d1fc1a94f4cbc217da0fb1fa132dca` | `3 / 0` |
| `frontend` | `npcink-ai-cloud-frontend:prod` | `sha256:4e100244d66dbcb7db24870b05ec5be4f6d34c48b9f08a3b254fd3e1a8a3e341` / `sha256:da173ebcb7cc836d5467e3d84092131f3fb26be967a83ab177f00d03976b96ab` | `e4d2e2098425737137d6ed01221730d9b99e695abf98aea2285c02e3ac5e44ec` / `371d6accd76affa0365abc8aa0e5235f44a4959fb4b03b15323e4881c351bf75` / `fdf5328442f503910034cf9cc3c7c3c63242f3874ebf36ce8af40a195747df53` / `6333dbd31c7a2c6a9f945ee51660c82d586a550afe999f9a3b19b34ff895597b` | `0 / 0` |
| `postgres` | `npcink-ai-cloud-postgres:prod` | `sha256:345c123c92481f5fa111cf2adb67bd584bce1743f66389d26cb4a742830f80e2` / `sha256:c02494f27f50e67cbb7df043ce570524fd54802ce664c7b97ecc6dc76a13d6d4` | `6a75c28ad33cd6d65529f91a04bd804b04b96f8ad9814c0215e08546dcc91251` / `7c95ef523a5be9b10be1d53179db89fa7cab20cd6d7dd7c410b7381c84fc9e27` / `c3f7b6f96a3cc8f95515823784010edc0018d4dd8a5797dccb9dd3c3c7306b0f` / `4da8bba51886dc8f27d89b68acd389120960fc1235ed0ee3e54ce2eda7666774` | `0 / 0` |
| `redis` | `redis:7-alpine@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99` / `npcink-ai-cloud-external-redis:prod` | `sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99` / `sha256:80dd823f4d2bf93dd5e418a0ae2817319a1ba279953e234082e54a5a18306223` | `71bcb5666a343fe3c06b5e33d3c243e1024cd78d9616b0c0cf13785e4ca8bf6d` / `6ad40231b28fe07334956cf42c68681bb676f050357565755d57d157472fc648` / `5c87a37c6edc5a1d39165ff8495174312d5fae7e84189ec16a5e7a197018cfea` / `39a7cea3f0e23b47104ce6d72d908d894ba967246880a9e04de61dac0db47d98` | `0 / 0` |
| `nginx` | `nginx:1.30-alpine-slim@sha256:ddde39c6e51f02fde7410c2e9c234cf2d0a4c7bdbbe176aeb37d8ad7ab4eb58c` / `npcink-ai-cloud-external-nginx:prod` | `sha256:ddde39c6e51f02fde7410c2e9c234cf2d0a4c7bdbbe176aeb37d8ad7ab4eb58c` / `sha256:478dc5ea554e53320fa53e33d2bf7dbf36f72d399f9822dd86a26c32f4953839` | `6adbe1489b5de24990517cd53856cb58461440a7d268e323381c4c5c70e290b2` / `1ceff45969c77f46766a5ec7bbea4ea29034bb76d0d5455f868854648c3622c9` / `a73d9a21410563a12e7a37c55ba70fbe661ef030f1d21cf77c2b17c42d9b8689` / `d2d5842932abc0aa2701922c641d91e6ea4f60ba73ffed344bcc4f93560e4640` | `0 / 0` |

The API receipt is `passed` only because the following exact findings match
the approved temporary entries: `CVE-2026-11940`, `CVE-2026-11972`, and
`CVE-2026-15308`, each for `python 3.14.6`. Owner is `Muze`; expiry is
`2026-08-05`; scope is P5 engineering scan and exact-bundle rehearsal only.
The exception grants no production or GA permission. The removal trigger is a
fresh scan of a rebuilt exact API image based on the first supported stable
3.14 build containing the relevant official backports.

The original unaccepted failure evidence remains unchanged at
`/private/tmp/p5b5-release-scan.VFYuau`: receipt SHA-256
`4538cc26ef1df61c48b7f21c5437ea86ec0e0106b00713567a4bcf9c45569091`
and Grype report SHA-256
`6fbc33854e6367b5b1afeb1d2720294384ebc63834baf815ee68ce64b9203bcc`.
That receipt still says `failed`, with three blocking and three unallowlisted
findings. It was not rewritten into success evidence.

## Exact Replay Evidence

The accepted bundle passed archive verification before extraction and then
passed this sequence in an isolated Compose project on port `18110`:

1. pre-load verification;
2. load five archives and verify all portable Config IDs after load;
3. start Postgres, Redis, API, frontend, and NGINX with `--pull never` and
   `--no-build` behavior;
4. prove Caddy, Jaeger, and the OTel Collector are absent;
5. repeat steps 1-4 using the same bundle without rebuilding;
6. prove the outer bundle receipt remained
   `592d1ce23334cddf4a09db0f147d6db48aa1c696980adc24630ed333660baa17`;
7. migrate a fresh database through Alembic head `20260717_0068`;
8. start the worker, callback worker, and ops worker from the API archive;
9. seed the smoke account/site/catalog and prove six provider health records
   healthy with no degraded or unhealthy record;
10. pass the live API smoke and final archive verification.

The existing development Compose container-set SHA-256 was
`2eccafea2475855f93ec5d9f361f464311c9b585394ae9fc504af771af7b9ad3`
both before and after replay. The bundle SHA-256 was also identical before and
after. The isolated smoke containers, network, volumes, temporary extraction,
and port listener were absent after cleanup. No broad Docker cleanup was run.

## Fail-Closed Defects Found And Closed

The acceptance flow was allowed to expose defects rather than bypass them:

- `eb548b6a` made empty build-cache arrays portable to macOS Bash 3.2,
  preserved the original EXIT status, made the outer smoke stop on bundle
  failure, and rejected an old bundle whose revision did not match HEAD.
- The first full scan then exposed a Bash 3.2 local-initialization bug that
  checked `.image.tar` instead of `api.image.tar`. `0ccbe9b4` split the local
  assignment and locked the behavior in the exact-bundle contract.
- A later attempt stopped on a transient Grype database download
  `unexpected EOF`; no stale database or prior receipt was reused.
- The next full scan exposed a verifier mismatch between a locked
  `name:tag@digest` input and Docker's canonical `name@digest` RepoDigest.
  `0663d95f` aligned final verification with the already fail-closed scanner
  rule while continuing to reject a wrong repository, local release alias, or
  wrong digest.

Independent review found no remaining P0/P1/P2 issue in either contract fix.
Every failed run exited nonzero and produced no candidate final bundle.

## Verification Gates

| Gate | Result |
| --- | --- |
| clean-tree image/deploy preflight | passed; `62` focused contracts |
| final exact-bundle and image-supply contracts | `46 passed` |
| focused Ruff | passed |
| shell syntax, Bash 3.2 probes, and `git diff --check` | passed |
| canonical image-lock offline verification | passed |
| full clean-tree build and five-subject release scan | passed |
| bundle pre-load and archive verification | passed |
| same-bundle double load and post-load verification | passed twice |
| migration, worker start, seed, health, and live smoke | passed |
| cleanup and existing-development-stack isolation | passed |
| independent contract reviews | no open P0/P1/P2 finding |

The full Cloud gates and the strict six-repository matrix are intentionally not
claimed here; they are P5-B8/final-closeout gates and must run against the
final current revision after WordPress and restore evidence is complete.

## Remaining Boundaries

P5-B7 does not prove or authorize:

- an `linux/amd64` artifact or deployment to the eventual production host;
- production Edge, DNS, WAF, TLS renewal, OTLP, secrets/config carry-forward,
  or rollback execution;
- WordPress text or media review/apply/restore on the current exact packages;
- production backup, RPO/RTO, penetration testing, live-provider credentials,
  real-user value, or production traffic;
- removal of the temporary Python CVE exceptions before their expiry;
- global P5 completion, release promotion, or GA.

The next batch is P5-B8: current exact WordPress package replay for text and
media, an isolated backup/restore drill, complete Cloud/plugin gates, a strict
six-repository matrix against the correct Cloud worktree, dependency follow-up,
and the final append-only P0-P5 requirement-to-evidence audit.
