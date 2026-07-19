# P5-B5 Exact Release Bundle v1

Status: engineering contract; a clean-daemon release rehearsal and production
operator evidence are still required.

## Purpose and boundary

P5-B5 defines one immutable handoff from a clean Cloud Git tree to an
offline-capable Docker deployment. It prevents a release from mixing source
revisions, rebuilding worker roles, omitting external services, changing CVE
exceptions, or pulling/building images during remote startup.

This is release-plane evidence only. It does not change Cloud runtime
ownership, WordPress governance, approval, audit, or final-write boundaries.

## Formal build contract

`deploy/bundle-images.sh` fails before its first Docker operation unless all of
the following are true:

- the Git worktree is clean, with no bypass;
- the canonical, committed `deploy/image-lock/production-images.json` and
  `deploy/image-lock/cve-allowlist.json` are used;
- `DOCKER_HOST`, `DOCKER_CONTEXT`, and image-lock overrides are absent;
- the target is resolved to exactly `linux/amd64` or `linux/arm64`;
- package extras are production-only: empty or `[zilliz]`;
- frontend and every locked external image are included.

Only Git-tracked files from `git archive HEAD` enter the source payload. The
manifest records the full commit/tree/branch, hashes of the Python and pnpm
locks, production Dockerfiles (including `Dockerfile.postgres`), Compose
files, migrations, `deploy/`, and `site/`, plus BuildKit secret IDs but never
secret values.

Formal images are built with local Buildx and an explicit platform. The API is
built once; `api`, `worker`, `callback_worker`, and `ops_worker` reuse one API
archive and manifest-declared aliases. Frontend and the derived Postgres image
are each built once. Compose externals are pulled by upstream digest, tagged
to the lock's deterministic `npcink-ai-cloud-external-*:prod` release alias,
and never represented by a mutable upstream tag.

## Scan and portable image identity

The complete release set is scanned after the single build/pull phase and
before packaging. A release scan must cover API, frontend, derived Postgres,
and every Compose external on the same selected platform and local Docker
context.

The scanner produces one Docker archive per scanned image and scans that exact
archive with pinned Syft and Grype. The bundle compresses those same archive
bytes; it does not run a second `docker save`. Receipts distinguish:

- the source daemon image ID, which may be a multi-architecture index digest;
- the portable Docker archive Config image ID, which is re-derived from a
  post-load `docker image save`; a target daemon's reported `.Id` is not
  assumed to equal this portable content identity;
- the upstream requested digest, deterministic release alias, archive hash,
  platform, scanner versions, database identity, SBOM/report hashes, and
  governed policy hashes.

The release index and every receipt must bind to the SHA-256 of the bundled
canonical image lock and CVE allowlist. Grype database freshness is enforced
when the receipt is created. Persistent bundle verification checks the ordered
timeline `database -> receipt -> index -> bundle creation`; it does not expire
an otherwise valid rollback artifact merely because wall-clock time passed.
A future-dated bundle remains invalid.

## Bundle layout

Generated outputs remain ignored under `dist/`:

```text
dist/deploy-bundle.tgz
dist/deploy-bundle.tgz.sha256
```

The archive contains at least:

```text
release-bundle-manifest.json
SHA256SUMS
Dockerfile
Dockerfile.postgres
frontend/Dockerfile
docker-compose.prod.yml
docker-compose.runtime.yml
deploy/image-lock/**
deploy/**
release/image-scan/**
scripts/production-image-supply.py
scripts/verify-release-bundle-manifest.py
site/**
dist/*.tar.gz
```

`npcink.release-bundle.v1` records every payload path, size, SHA-256, image
role, load reference, upstream source reference, source daemon ID, portable
load ID, platform, scan evidence, and source inputs. `SHA256SUMS` covers every
regular payload file except itself, including the manifest. Verification
rejects missing/extra/duplicate files, symlinks, special files, absolute or
traversal paths, non-canonical separators, controls, and oversized archives
before extraction.

The outer `.tgz.sha256` travels with the bundle. It is integrity evidence, not
an authenticity signature; deployment authorization remains governed by the
production release policy.

## Verification and deployment order

```bash
bash deploy/verify-release-bundle.sh --archive \
  dist/deploy-bundle.tgz dist/deploy-bundle.tgz.sha256

bash deploy/verify-release-bundle.sh --pre-load /path/to/extracted-release
bash deploy/verify-release-bundle.sh --post-load /path/to/extracted-release
```

The fail-closed order is:

1. Verify the local archive, full manifest, scan receipts, policy hashes, and
   target platform before upload.
2. Upload to a unique incoming directory and verify remotely before extraction.
3. Acquire the remote deployment lock and extract into a unique release path.
4. Verify the extracted payload before the first `docker load`.
5. Load every primary archive once, add only declared aliases, and verify every
   portable image ID before Compose.
6. Start with both `--pull never` and `--no-build`.
7. Run migration/readiness gates, then atomically promote the `current` link.

`deploy/bundle-images.sh` has no remote-Docker build mode. SSH is only a
transport and deployment boundary for an already locally built and verified
bundle. `NPCINK_CLOUD_DEPLOY_SMOKE_SKIP_BUILD=1` is strict reuse: absent bundle
or checksum is an error, never an implicit rebuild.

## Acceptance boundary

Contract tests prove deterministic schema and rejection behavior. Freeze/GA
still requires a clean committed-tree run, an empty/classic-daemon
save-load-alias rehearsal, `docker compose --pull never --no-build`, the full
release scan, and recorded revision/tree/outer SHA-256. A real CVE gate failure
must remain failed; it must not be bypassed to manufacture release evidence.

## Current Engineering Status — 2026-07-19

The production-topology precondition passed at implementation revision
`fb58e354`; see
[P5-B6 Production Topology Contraction Closeout](p5-b6-production-topology-contraction-closeout-2026-07-19.md).
Caddy, Jaeger, and the OpenTelemetry Collector are no longer active bundle
inputs. This does not close this exact-bundle contract: the clean-tree platform
scan, governed resolution of the current API-image CVE failure, archive build,
verification, save/load/alias replay, and recorded revision/tree/outer digest
remain required.
