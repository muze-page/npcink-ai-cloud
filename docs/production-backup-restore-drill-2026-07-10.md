# Production Backup Restore Drill - 2026-07-10

Status: passed.

## Objective

Prove that a current production PostgreSQL backup can be checksum-verified,
restored without overwriting the live database, queried, exported again, and
cleaned up while production remains available.

This drill did not modify application code, `.env.deploy`, production rows, or
Cloud/WordPress ownership boundaries.

## Backup Artifact

- Host: production release host for `https://cloud.npc.ink`
- Path:
  `/opt/npcink-ai-cloud/backups/pre-release-restore-drill-20260710T102412Z.dump`
- Format: PostgreSQL custom archive (`pg_dump --format=custom`)
- Size: `3,011,736` bytes
- Mode: `0600`
- SHA-256:
  `2f9ad9ec403b4c317c638d11e01d1bda0649ebe5410db5a27d9d2e95fb8f4db4`
- Checksum sidecar: the same path with `.sha256` appended

The archive list and SHA-256 check both passed before restore.

## Safety Controls

- The first approach used a separate no-network PostgreSQL container with a
  `256MiB` memory limit. The container reached its own cgroup limit while
  creating an index and was terminated by the kernel. Production PostgreSQL
  remained ready and the public health endpoint remained healthy.
- The successful approach used a strictly prefixed temporary database inside
  the existing production PostgreSQL cluster. This avoided a second PostgreSQL
  process on a host with `1.8GiB` RAM and no Swap.
- The script rejected any database name not beginning with
  `npcink_restore_drill_` and rejected the real production database name.
- A shell exit trap ran `dropdb --if-exists` on success and failure.
- No application process was pointed at the temporary database.

The low-memory conclusion is operational: do not run a second PostgreSQL server
on the current host for restore drills. Use a strongly named temporary database
in the existing cluster, or restore on a separate host with adequate memory.

## Successful Run

- Started: `2026-07-10T10:29:06Z`
- Finished: `2026-07-10T10:29:10Z`
- Temporary database:
  `npcink_restore_drill_20260710T102906Z`
- Source migration: `20260710_0057`
- Restored migration: `20260710_0057`
- Public tables readable: `54`
- `site_user_grants` absent: yes
- Plans:
  `free:active,plus:active,pro:active,agency:active`
- Accounts: `3`
- Sites: `3`
- Account memberships: `1`
- Account subscriptions: `3`
- Service settings: `3`
- Service settings containing encrypted secret payloads: `2`
- Restored schema export: passed
- Restored data export: passed
- Temporary database removed after verification: confirmed
- Production services running after cleanup: `11`
- Production PostgreSQL readiness after cleanup: passed
- Public health after cleanup: `healthy`

The Portal public setting has no secret payload, so two encrypted service
settings out of three is the expected production state.

## Reproduction Pattern

Use the exact backup path selected for the incident or drill. Never substitute
the production database name for `drill_db`.

```bash
backup=/opt/npcink-ai-cloud/backups/<verified-backup>.dump
postgres_container=npcink-ai-cloud-postgres-1
drill_db="npcink_restore_drill_$(date -u +%Y%m%dT%H%M%SZ)"
production_db=$(docker exec "$postgres_container" \
  sh -lc 'printf "%s" "$POSTGRES_DB"')

case "$drill_db" in
  npcink_restore_drill_*) ;;
  *) exit 1 ;;
esac
test "$drill_db" != "$production_db"

cleanup() {
  case "$drill_db" in
    npcink_restore_drill_*)
      docker exec "$postgres_container" \
        sh -lc 'dropdb -U "$POSTGRES_USER" --if-exists "$1"' \
        sh "$drill_db" >/dev/null 2>&1 || true
      ;;
  esac
}
trap cleanup EXIT

docker exec "$postgres_container" \
  sh -lc 'createdb -U "$POSTGRES_USER" "$1"' sh "$drill_db"

docker exec -i "$postgres_container" \
  sh -lc 'pg_restore -U "$POSTGRES_USER" -d "$1" \
    --no-owner --no-acl --exit-on-error' sh "$drill_db" < "$backup"

# Verify migration, critical rows, schema export, and data export here.
```

For a real recovery, first stop or fence all writers, restore into a replacement
database, validate it, and use a controlled configuration/traffic switch. Do
not restore directly over the live database.
