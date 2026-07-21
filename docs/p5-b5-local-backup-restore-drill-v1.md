# P5-B5 Local Backup Restore Drill v1

Status: active engineering gate.

## Purpose

This contract proves that the current Cloud database and local-volume
ArtifactStore can be captured as one recovery point, rejected when incomplete
or corrupt, and restored into completely fresh local resources.

It closes a gap left by the production database-only drills recorded on
[2026-07-10](production-backup-restore-drill-2026-07-10.md) and
[2026-07-11](production-backup-restore-drill-2026-07-11.md): media artifact
metadata is useful only when the matching bytes are recoverable too.

This is an engineering release gate. It is not production backup evidence, a
production runbook, or authorization to contact or modify a deployed service.

## Entry Point

From the repository root:

```bash
deploy/backup-restore-drill.sh | tee /tmp/p5-b5-backup-restore-drill.json
```

The command performs the actual drill by default. `--help` is the only
non-executing mode.

Optional, non-secret overrides are deliberately narrow:

- `NPCINK_RESTORE_DRILL_POSTGRES_IMAGE`: PostgreSQL 16 image, default
  `postgres:16-alpine`;
- `NPCINK_RESTORE_DRILL_TIMEOUT_SECONDS`: readiness timeout from 10 to 900
  seconds, default `90`;
- `NPCINK_RESTORE_DRILL_PYTHON`: Python executable containing this repository's
  locked development dependencies, default `.venv/bin/python`.

The current repository head when this contract was written is
`20260717_0068`. The script does not freeze that literal. It parses every
migration revision and parent with Python AST, requires exactly one graph head,
applies `upgrade head`, and then requires both source and restored
`alembic_version` to equal the graph head discovered for that run.

## Isolation And Safety Contract

Every run must:

- create a high-entropy resource prefix containing time, PID, and Bash random
  data so concurrent runs do not share containers, volumes, or networks;
- create a source PostgreSQL 16 container and named volume, then destroy both
  before creating the restore container and fresh restore volume;
- publish PostgreSQL only on a Docker-selected loopback port;
- resolve the active Docker endpoint before `docker info`, require a local Unix
  socket, and reject SSH, TCP, and other remote Docker transports before any
  resource can be created;
- run Alembic from an empty temporary working directory through `env -i`, with
  only a generated local database URL and non-secret process settings;
- never source or copy `.env`, `.env.local`, `.env.deploy`, Compose
  configuration, or production credentials;
- never accept a database URL, hostname, container name, volume name, or network
  name from the operator;
- install an `EXIT`, `INT`, `TERM`, and `HUP` trap before creating Docker
  resources;
- remove both containers, both volumes, the network, and the temporary working
  directory on success or failure;
- verify Docker resources are absent before reporting success.

The fixed database credential is generated for the disposable run and is not a
real secret. No provider, Portal, admin, runtime-signing, payment, or WordPress
credential is required.

## Recovery Point

The source database is migrated before it is seeded. The representative graph
is intentionally small but relational:

```text
account -> membership -> principal
   |
   +-> WordPress site -> hosted media run -> media artifact -> delivery evidence
```

The artifact row points to bytes written through the real
`LocalVolumeArtifactStore`, including its private generation and publication
fence files.

The recovery point contains:

- a PostgreSQL custom-format dump produced with `pg_dump --format=custom`,
  without owner or ACL restoration;
- a deterministic database manifest covering the migration revision, every
  representative row, and the joined relationship count;
- an ArtifactStore tar archive;
- portable tar creation with macOS AppleDouble metadata disabled, so archive
  contents remain identical to the source store inventory;
- a deterministic per-file ArtifactStore manifest with path, mode, byte size,
  and SHA-256;
- SHA-256 for both archives and both manifests;
- a JSON recovery-point manifest binding the database and ArtifactStore
  evidence to the same Alembic head and PostgreSQL image input.

All generated files use restrictive process umask and remain under the
temporary directory. They are not committed and are removed after the summary
is emitted. The caller may persist the stdout JSON with `tee`; the archives
themselves are deliberately ephemeral.

## Mandatory Failure Injection

A passing run must prove both negative paths before restoring:

1. append bytes to a copy of the database dump and prove its expected SHA-256
   rejects the damaged copy;
2. extract a copy of the ArtifactStore archive, delete the database-referenced
   object, regenerate the manifest, and prove exact manifest comparison rejects
   the incomplete copy.

An unexpected pass in either negative path fails the drill. The restore also
fails closed if an archive, manifest, recovery manifest, migration head,
PostgreSQL major version, row graph, file mode/size/hash, or database-to-file
artifact metadata differs.

## Fresh Restore Acceptance

After source destruction, the drill must:

- start a fresh PostgreSQL 16 container backed by a different empty named
  volume;
- checksum every recovery-point component immediately before use;
- restore the custom archive with `pg_restore --exit-on-error --no-owner
  --no-acl`;
- require the restored Alembic revision to equal the run's discovered head;
- require the restored database manifest to byte-match the source manifest;
- require the complete account-to-delivery join count to remain exactly one;
- safely extract the ArtifactStore archive into a new empty directory while
  rejecting absolute paths, traversal, links, devices, and other non-regular
  entries;
- require the restored ArtifactStore manifest to byte-match the source
  manifest;
- recompute the restored referenced object's size and SHA-256 and require both
  to match the restored database row.

## Machine-Readable Result

Success writes one JSON object using contract
`p5_b5_backup_restore_drill.v1`. It includes:

- exact discovered Alembic head;
- requested PostgreSQL image, local image ID, and server version number;
- hashes for the database dump, database manifest, ArtifactStore archive,
  ArtifactStore manifest, and combined recovery manifest;
- both required failure-injection results;
- database and ArtifactStore manifest equality plus relationship count;
- verified Docker cleanup posture;
- verified local Docker Unix-socket posture;
- `production_contacted: false`.

The success object is buffered in memory, the temporary working directory is
removed and verified absent, and only then is the object written to stdout.
Signal handlers convert `HUP`, `INT`, and `TERM` into nonzero exits before the
single `EXIT` cleanup path emits failure evidence.

Failure exits non-zero and writes a smaller JSON object with the failed stage,
exit code, resource prefix, and `production_contacted: false`. Logs go to
stderr so stdout can be retained as structured evidence.

## Boundary And Non-Goals

The drill remains inside the approved `PostgreSQL + Docker Compose-era local
volume` operational boundary. It adds no scheduler, registry, CMS write path,
cloud control-plane truth, or production infrastructure. WordPress remains the
only CMS write owner; the seeded media result is `suggestion_only` evidence.

It does not:

- read, back up, restore, rotate, or validate production secrets;
- connect to production or reuse a production Docker resource;
- prove production RPO, RTO, retention, off-host storage, encryption, or
  operator readiness;
- replace a pre-release operator backup made from fenced production writers;
- authorize a production deployment or GA claim.

## Verification

```bash
bash -n deploy/backup-restore-drill.sh
.venv/bin/python -m pytest tests/contract/test_backup_restore_drill_contract.py
```

For release engineering acceptance, run the actual command once with Docker
available, save only its stdout JSON under `/tmp`, and independently confirm
that the reported resource prefix no longer resolves as a Docker container,
volume, or network.
