# ADR-022: Validate RDS PostgreSQL 18 After Refactor Before Production Adoption

## Status

Accepted as the preferred post-refactor evaluation direction. The trial is not
authorized and remains deferred pending explicit priority, budget, and operator
approval.

## Date

2026-07-20.

## Context

Npcink AI Cloud currently runs PostgreSQL 16 as part of the production Docker
Compose stack. PostgreSQL is the canonical durable truth for runtime records,
commercial and usage evidence, idempotency, audit events, artifact metadata,
and worker coordination. Redis remains short-lived wake-up and coordination
support.

The current implementation and evidence are version-specific:

- development, runtime, production, and isolated proof Compose files use
  `postgres:16-alpine`;
- the media artifact concurrency proof explicitly requires PostgreSQL major 16;
- encryption, migration, semantic upgrade/downgrade, backup, and restore
  rehearsals have been completed on PostgreSQL 16;
- the production database observed on 2026-07-20 was PostgreSQL 16.14, about
  147 MB, with seven active database connections and only the built-in
  `plpgsql` extension installed.

RDS PostgreSQL 18 is now a supported Alibaba Cloud offering and has a longer
upstream support runway than PostgreSQL 16. It also includes the cumulative
PostgreSQL 17 and 18 improvements to vacuum memory use, SQL/JSON, logical
replication, asynchronous I/O, index skip scans, generated columns, UUIDv7,
and observability. The current Cloud workload does not yet demonstrate a
performance need for those capabilities, but choosing version 18 for a new
long-lived managed database could avoid an earlier future major-version
upgrade.

Moving directly from the self-managed PostgreSQL 16 database to RDS
PostgreSQL 18 combines two changes: the hosting boundary changes from a local
container to a managed VPC service, and the database major version changes.
Alibaba Cloud one-click physical cloud migration requires the source and target
major versions to match, so a direct 16-to-18 move must instead use a separately
validated dump/restore, DTS, or logical migration path.

## Decision

Keep PostgreSQL 16 unchanged throughout the current GA-preparation stage. Do not
purchase RDS, change production database configuration, update Compose images,
or relax the PostgreSQL 16 proof gates without a separately approved trial.

After the accepted refactor closeout, and only when the infrastructure trial is
explicitly prioritized and funded, use RDS PostgreSQL 18 as the preferred
candidate for a bounded pre-production compatibility and recovery trial:

1. Create a temporary, target-representative RDS PostgreSQL 18 instance in the
   same region and VPC as the application host, using a private endpoint.
2. Prove both a fresh Alembic install and a PostgreSQL 16 production-like
   dump/restore into PostgreSQL 18.
3. Run the current application, workers, migrations, concurrency proofs,
   commercial idempotency checks, and recovery gates against PostgreSQL 18.
4. Adopt RDS PostgreSQL 18 for formal production only if every acceptance gate
   below passes and the operator separately approves the purchase and cutover.
5. If compatibility, recovery, performance, cost, or schedule gates do not
   pass, retain PostgreSQL 16 or use RDS PostgreSQL 16 as the low-change managed
   fallback.

This ADR accepts the evaluation sequence and preferred candidate. It does not
authorize a purchase, production migration, database major-version change,
deployment, or production cutover.

## Entry Conditions

The PostgreSQL 18 trial must not begin until all of the following are true:

- the current refactor is complete and has an explicit accepted closeout;
- the application migration head and production topology are stable;
- `master` CI and the required Cloud release gates are green;
- a current production-like data inventory exists;
- a checksum-verified and restore-tested PostgreSQL 16 backup exists together
  with the matching application revision and runtime-data encryption key;
- the operator has approved the temporary RDS spend and trial window;
- current Alibaba Cloud PostgreSQL 18 regions, editions, specifications,
  extensions, migration methods, backup features, and pricing have been
  re-verified rather than copied from this dated decision record.

## Required Validation

The trial must include all of the following evidence:

### Schema and migration

- create an empty PostgreSQL 18 database and apply the complete Alembic history;
- restore a current PostgreSQL 16 custom-format dump into a separate
  PostgreSQL 18 database;
- verify Alembic head, table and index inventory, constraints, sequences, row
  counts, and selected checksums;
- review every warning emitted by `pg_dump`, `pg_restore`, RDS, and Alembic;
- verify PostgreSQL-specific partial indexes, `ON CONFLICT` backfills, JSON
  fields, timestamp behavior, and collation-sensitive identifiers.

### Runtime correctness

- run `pnpm run check:fast`;
- run `pnpm run check:seam`;
- run `pnpm run check:anti-drift`;
- run the narrow migration, payment, credit-ledger, runtime idempotency,
  callback, and media artifact lifecycle suites;
- extend the isolated PostgreSQL proof to cover PostgreSQL 18 semantics instead
  of merely changing the hard-coded major-version assertion;
- prove simultaneous worker claims, `FOR UPDATE SKIP LOCKED`, stale-claim
  fencing, artifact delivery versus purge coordination, and payment/order row
  locking.

### Performance and operations

- compare the six current runtime hot-path query plans and timings between
  PostgreSQL 16 and the target RDS PostgreSQL 18 instance;
- run the normal API and worker topology for at least 24 hours and inspect
  connection stability, error rate, lock waits, database CPU, memory, I/O, and
  storage growth;
- verify application connection retry behavior across an RDS restart and, when
  testing the target high-availability edition, a controlled primary/standby
  switchover;
- configure and verify automatic backups and the intended log-backup or
  point-in-time recovery posture for the selected edition;
- restore a managed backup into an isolated instance and verify readable
  application inventory with the matching application revision and encryption
  key;
- record the complete monthly price, including compute, storage, backups,
  monitoring, and optional services.

### Promotion gate

Production adoption requires one explicit operator review confirming that:

- every required validation item passed;
- no unresolved PostgreSQL 18 compatibility or query-plan regression remains;
- the RDS edition and specification match the required availability posture;
- the rollback recovery point and maintenance window are known;
- `docs/cloud-production-release-policy-v1.md` is satisfied;
- a separate production cutover plan has been reviewed and approved.

## Alternatives Considered

### Move immediately to RDS PostgreSQL 16

This remains the low-change fallback. It preserves the current validated major
version and enables a same-version managed migration, but it has a shorter
remaining support runway and creates a likely major-version upgrade milestone
sooner.

### Move directly to RDS PostgreSQL 18 without a trial

Rejected. The project has no PostgreSQL 18 migration, concurrency, encrypted
data, backup/restore, or production-like soak evidence. Combining the hosting
and major-version changes without isolating compatibility risk is not justified
by the current workload.

### Change the Cloud database to MySQL

Rejected. The current PostgreSQL schema, migrations, partial indexes, raw SQL,
locking proofs, and operational procedures would require a broad rewrite with
no demonstrated user-facing benefit.

### Perform the PostgreSQL 18 work during the current refactor

Rejected. Database infrastructure and major-version work would expand the
refactor boundary, make failures harder to attribute, and delay the current
product closeout.

## Consequences

- The current refactor and production runtime remain on the proven PostgreSQL
  16 baseline.
- PostgreSQL 18 is not treated as production-ready for this project until the
  explicit trial passes.
- A successful trial can provide a longer version-support runway and avoid an
  earlier post-launch major-version upgrade.
- The trial adds temporary RDS cost and one bounded engineering cycle.
- Failure of the PostgreSQL 18 trial does not block the managed-database path;
  RDS PostgreSQL 16 remains available as the fallback.
- Future agents must not interpret this ADR as authorization to edit production,
  buy cloud resources, weaken PostgreSQL 16 assertions, or start migration work
  before the entry conditions are met.

## Rollback

The compatibility trial must not replace or mutate the PostgreSQL 16 source
database. If the trial fails, preserve the evidence report, stop using the
temporary PostgreSQL 18 target, and retain the PostgreSQL 16 runtime.

A later production cutover requires its own rollback procedure. At minimum it
must fence all writers, retain the matched PostgreSQL 16 backup, application
revision, and encryption key, validate the PostgreSQL 18 target before traffic
switching, and define the accepted treatment of writes made after cutover.

## References

- [Production Compose](../../docker-compose.prod.yml)
- [Production Operations Playbook](../../deploy/OPS_PLAYBOOK.md)
- [Production Release Policy](../cloud-production-release-policy-v1.md)
- [Runtime Stability and Performance Evidence](../runtime-stability-performance-evidence-v1.md)
- [P5-B2 Security Hardening Closeout](../p5-b2-security-hardening-2026-07-17.md)
- [Persistent Fenced Media Artifact Orphan Cleanup](015-persistent-fenced-media-artifact-orphan-cleanup.md)
- [Alibaba Cloud RDS PostgreSQL version lifecycle](https://help.aliyun.com/en/rds/apsaradb-rds-for-postgresql/lifecycles-of-major-engine-versions)
- [Alibaba Cloud RDS PostgreSQL feature overview](https://help.aliyun.com/zh/rds/apsaradb-rds-for-postgresql/features-of-apsaradb-rds-for-postgresql)
- [Alibaba Cloud one-click PostgreSQL cloud migration](https://help.aliyun.com/en/rds/apsaradb-rds-for-postgresql/use-the-cloud-migration-feature-for-an-apsaradb-rds-for-postgresql-instance)
- [PostgreSQL 17 release](https://www.postgresql.org/about/news/postgresql-17-released-2936/)
- [PostgreSQL 18 release](https://www.postgresql.org/about/news/postgresql-18-released-3142/)
