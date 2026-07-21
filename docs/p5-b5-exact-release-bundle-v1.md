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

The formal builder must expose `docker image inspect --platform` and
`docker image save --platform`, with Docker server API 1.49 or newer. This is
a build/scan requirement, not a production-host requirement: the target host
only loads the already verified single-platform archives.

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

- the daemon-reported image ID for the explicitly selected platform, which may
  differ from the portable archive Config image ID across Docker image stores;
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

In both bundled production Compose files, every governed service image,
including `release-one-off`, must use its exact
`${NPCINK_CLOUD_*_RELEASE_IMAGE:-governed-default}` seam. A literal mutable
tag is rejected even when it happens to equal the governed default.

`npcink.release-bundle.v1` records every payload path, size, SHA-256, image
role, load reference, upstream source reference, source daemon ID, portable
Config image ID, platform, scan evidence, and source inputs. `SHA256SUMS` covers
every regular payload file except itself, including the manifest. Verification
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
   portable Config image ID before Compose.
6. Select one explicit loader phase: `prepare-only`, `data-only`, `api-only`,
   `workers-only`, or `traffic-only`. There is no default or aggregate loader
   phase; a missing or unknown value fails before mutation.
7. For each mutating loader phase, freeze the whole batch's daemon IDs, create
   the complete batch as stopped candidates with `--pull never`, `--no-build`,
   and `--no-start`, then prove the whole batch before starting captured IDs.
8. Stop the old application/write services, start and verify the data batch,
   then run migration and provider refresh through the staged one-off API.
9. Only after migration and provider refresh pass, atomically promote the
   `current` link to the staged release.
10. After the pointer switch, start and verify the API batch, then the workers
    batch, prove release-specific and generic operational readiness, and only
    then restore the traffic batch.

The pointer therefore switches after migration and before API, workers, or
operational-readiness validation; it is not a final action after readiness.

Post-load verification saves each primary role once by its immutable
target-daemon ID, re-proves the manifest's platform plus portable Config image
ID, checks all declared aliases, and atomically publishes the bundle-bound map
at the deterministic, non-configurable path
`.release-state/<release-name>/target-daemon-images.json` beside the release
directory. Both `.release-state` and its `<release-name>` child must already be
owner-controlled non-symlink directories with mode `0700`; the map must be an
owner-controlled non-symlink regular file with mode `0600`. Both read and write
paths reject a map larger than 256 KiB. It is outside the release payload, and
neither an environment variable nor a CLI option may redirect it. Its binding
includes the release instance name and canonical resolved release path in
addition to manifest, checksum, revision, and platform evidence. An unsafe,
oversized, malformed, copied from a different release path or instance,
tampered, or differently bundle-bound existing map is rejected instead of
overwritten.
`loaded-role-daemon-id` validates that map against the extracted manifest and
current governed tag before a migration, provider refresh, data-service switch,
or cutover one-off runs. Runtime containers are compared only with this proved
target-local ID. Neither the portable Config image ID nor the source daemon ID
is treated as the target daemon's `.Id`.

`prepare-only` is the only loader phase that runs the full pre-load and
post-load payload verification and publishes this map. Later phases in the
same deployment-lock transaction deliberately do not re-hash every large image
archive. Their trust boundary is the same exact release root: it must remain
operator-owned and not group/world writable, production policy forbids direct
server-side application-code edits, and every role lookup still revalidates the
map's release/bundle binding plus the current governed tag before container
proof. If that release-root trust cannot be proved, the phase must stop; the
operator must rerun `prepare-only` and the full verifier rather than continue
from the map alone.

For every service-start phase, the loader first freezes every required role's
daemon ID from that fixed map and pins the corresponding Compose image value to
the immutable ID. Compose then uses
`up --no-start --pull never --no-build --no-deps --force-recreate` to create all
requested services as stopped candidates. For each of the `data-only`,
`api-only`, `workers-only`, and `traffic-only` batches, the loader captures
exactly one candidate container ID per service, verifies each candidate's
`.Image`, `created` state, and zero restart count, and re-proves every governed
tag against the map only after the complete candidate set exists. Only after
the whole batch passes does it run `docker start` on those captured container
IDs; post-start checks must prove the same IDs are running with the same images
before health or readiness can pass. A failed whole-batch proof removes the
stopped candidates or retains recovery evidence when cleanup cannot be proved.
`prepare-only` never starts a service.

Migration and provider refresh use the profiled `release-one-off` API service
with the same stopped-candidate rule. The payload runs through `docker exec -i`
only after the stopped candidate and governed tag match the recorded daemon ID,
the captured container ID has been started, and that same running identity has
been rechecked. A fixed private lock under the managed `.release-state` root
serializes one-offs across release directories and is retained when cleanup
cannot be proved.

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
