# Cloud First Install Contract v1

Status: active.

## 1. Purpose

Define the only supported production first-run path for Npcink AI Cloud:

`deploy -> prove host control -> validate empty PostgreSQL 18 -> migrate -> generate secrets -> reveal admin key once -> activate runtime`

This is infrastructure bootstrap for the hosted runtime. It is not a WordPress,
CMS, provider, payment, or workflow configuration console.

## 2. Installation state

The canonical installation state is a protected host file, not database reachability:

- `pending`: setup is available; ordinary Cloud surfaces fail closed;
- `initializing`: one installer owns the exclusive lock; other writes conflict;
- `complete`: runtime configuration is authoritative and setup writes are gone.

An ordinary validation or migration failure returns to `pending` while retaining
only bounded, non-secret interrupted-attempt evidence. A completed installation
never returns to `pending` automatically. Database failure after completion is a
runtime outage and recovery event.

The application never infers `pending` from an absent `install-state.json`.
Only the root-owned host preparation helper may create the first explicit
`pending` state, while it holds the shared installation lock and has proved
that no runtime artifact, permanent completion sentinel, or conflicting
first-install lifecycle exists. Missing or corrupt installation evidence
therefore fails closed and never reopens Setup.

`GET /setup/v1/state` remains available after completion and returns only the
minimal `complete` projection required by the frontend gateway. The `/setup`
page and all other setup endpoints return `404 setup.already_complete` after
completion.

## 3. Bootstrap and runtime configuration

The shared host configuration directory is mounted at `/run/npcink-config`:

| File | Contents | Mode |
|---|---|---:|
| `runtime-config.json` | RDS components and required runtime roots | `0600` |
| `install-state.json` | state, setup revision, timestamps, config digest | `0640` |
| `rds-ca.pem` | RDS server CA chain | `0600` |
| `setup-auth.json` | setup-code digest and transient session root | `0600` |
| `frontend/internal-auth-token` | dedicated internal-token projection for Admin BFF only | `0640` |

Writes use a same-filesystem temporary file, file `fsync`, atomic rename, and
directory `fsync`. Secret values are never passed through a shell command,
command-line argument, URL, log field, response error detail, or browser storage.

In production, `runtime-config.json` is the sole authority for the database and
root signing/encryption/session values. Duplicate production values in the
environment fail validation instead of silently overriding the file. Development
and test modes may explicitly use the existing environment source.

The completed runtime derives its trusted-host set from the configured public
origin plus the fixed Compose API service name and loopback hosts. This permits
Frontend BFF and operator probes to reach the non-published API container while
the external Edge continues to pin the public host. No wildcard or arbitrary
container hostname is accepted.

The frontend container mounts only the `frontend/` projection directory, not
`runtime-config.json`, the database password, the RDS CA, or any signing and
encryption root. Setup BFF code never reads or forwards the projected internal
token.

## 4. Setup authentication

The host preparation and rotation helpers generate:

- `nca_setup_` plus 32 random bytes encoded as unpadded URL-safe Base64;
- a separate transient setup-session signing root.

Only the SHA-256 digest of the setup code is stored. Automated deployment
deliberately does not emit the initially generated plaintext into CI output.
The operator issues a usable replacement through the active release's
`setup-code-rotate` helper, which requires an attached TTY, prints the plaintext
once, and refuses captured or non-interactive output. The frozen single API
worker limits `POST /setup/v1/session` to five failed attempts per source IP in
15 minutes with a process-local counter; a process restart clears that
defense-in-depth counter, while the unguessable 32-byte code remains the primary
control. A successful exchange issues a 15-minute `HttpOnly`, `Secure`,
`SameSite=Strict` cookie. The active digest and transient session root are
atomically retired before `complete` is committed; a protected tombstone makes
the pre-commit crash window recoverable and is deleted idempotently afterward.

Losing an unused code requires the operator-only `setup-code-rotate` command.
Rotation invalidates existing Setup cookies. If an interrupted attempt exists,
it retains only the attempt ID needed to recognize its database marker and
clears the old session-keyed idempotency/request fingerprints so the new
session can establish a fresh pair. There is no public setup reset or recovery
endpoint.

## 5. API contract

All responses use the existing Cloud envelope and snake_case fields.

### `GET /setup/v1/state`

Returns only:

- `installation_state`: `pending | initializing | complete`;
- `setup_revision`;
- `retry_allowed`.

It never returns paths, configuration fields, failure exception text, hostnames,
database identity, secrets, or previous input.

### `POST /setup/v1/session`

Input: `setup_code`.

Output: `installation_state` and `expires_in_seconds`; the authenticated state
is carried only by the setup cookie.

### `POST /setup/v1/database/test`

Requires the setup cookie. Input contains separate database fields:

- `host`, `port`, `database`, `username`, `password`;
- `ssl_mode`, fixed to `verify-full` in production;
- `ca_pem`.

The boundary validates the hostname, DNS resolution, private-address posture,
PostgreSQL major version, TLS identity, transaction/DDL privileges, database
emptiness, current Alembic state, connection latency, and `max_connections`.
The response returns sanitized facts only.

### `POST /setup/v1/install`

Requires the setup cookie and a valid `Idempotency-Key`. Input contains:

- `cloud_name`;
- an HTTPS `public_base_url` with no path, query, or fragment;
- the same database object accepted by the test endpoint.

`public_base_url` must exactly match one of the public origins approved in the
bootstrap environment. The installer cannot silently move the runtime to a
different host than the protected Setup page and frontend gateway.

Under the exclusive install lock it repeats validation, migrates to the current
Alembic head, generates runtime roots, builds and validates full Settings, writes
configuration atomically, proves full runtime-service construction, deletes
setup authentication, and only then commits `complete`.

Interrupted-attempt evidence stores only the SHA-256 digest of the idempotency
key and an HMAC-SHA256 of the canonical install request keyed by the transient
setup-session root. A retry must match both values. Neither the key, database
password, CA, nor a plain request digest is written to `install-state.json`.

The success response returns exactly one unrecoverable plaintext value:

- `admin_key`: `nca_admin_` plus 32 random bytes;
- `next_url`: `/admin/login`.

The server stores only `SHA-256(admin_key)`. A completed replay never reveals or
regenerates the key. If the success response is lost, the operator uses
`admin-key-rotate`.

Admin-key rotation publishes a bounded `admin_key_rotation.v1` transition in
`install-state.json`: the old and target runtime-config digests are accepted
only across the two atomic file replacements, then the old digest is removed.
An interruption before the new plaintext key is shown therefore keeps one
valid runtime configuration and a rerun safely supersedes the unknown key.

### `POST /admin/auth/login`

Replaces the development-era bootstrap endpoint. Input: `admin_key`. The server
compares its digest in constant time and then uses the existing single
`platform_admin` reference and an HttpOnly session cookie. A fresh empty
database has no persisted administrator grant: the root administrator is a
bounded synthetic identity whose authority comes from the admin-key digest.
Rotating the admin key also rotates the session-signing secret and restarts the
API, invalidating both the old key and every old cookie. If a persisted grant is
introduced later, the existing grant and session-version checks also apply; the
installer does not create a second administrator registry.

## 6. Error contract

Stable setup errors include:

- `setup.installation_required`
- `setup.session_required`
- `setup.code_invalid`
- `setup.rate_limited`
- `setup.installation_in_progress`
- `setup.request_invalid`
- `setup.route_not_found`
- `setup.idempotency_key_required`
- `setup.idempotency_key_invalid`
- `setup.idempotency_key_conflict`
- `setup.request_too_large`
- `setup.state_unavailable`
- `setup.public_origin_unavailable`
- `setup.public_base_url_mismatch`
- `setup.database_unreachable`
- `setup.database_tls_required`
- `setup.database_version_unsupported`
- `setup.database_not_empty`
- `setup.database_permissions_insufficient`
- `setup.migration_failed`
- `setup.config_write_failed`
- `setup.already_complete`
- `proxy.setup_route_not_allowed`
- `proxy.setup_unreachable`
- `auth.admin_login_request_invalid`
- `auth.admin_key_required`
- `auth.admin_key_not_configured`
- `auth.admin_key_invalid`
- `proxy.admin_login_invalid_response`

Internal exception messages, SQL, credentials, resolved IP lists, and filesystem
paths are never included in the public response.

## 7. Routing and health

Before completion:

- `GET /health/live` remains a minimal liveness response;
- `GET /health/ready` remains internal-only and reports not ready;
- setup state/session/test/install and required static frontend assets are the
  only public application paths;
- the frontend's exact `GET|HEAD /api/health` container-health route is also
  available; other methods and extension-shaped dynamic paths remain gated;
- Admin, Portal, public runtime, Open, and ordinary frontend BFF routes return
  `503 setup.installation_required`;
- workers wait for `install-state=complete` and do not connect to PostgreSQL.

After completion, `GET /health/live` remains independent of runtime
configuration and database activation. An RDS or protected-config failure makes
authenticated readiness return 503, but it never changes the canonical state
or makes Setup available again.

The frontend `/setup` route is outside the Admin layout. Its BFF has an explicit
method/path allowlist and forwards only the setup cookie; it never injects an
internal service token. Setup secrets remain in component memory and are never
written to URL parameters, localStorage, sessionStorage, analytics, or logs.

## 8. PostgreSQL 18 validation profile

The first external target is Alibaba Cloud RDS PostgreSQL 18 Basic Edition
`pg.n2e.1c.1m`. Validation defaults are:

- one API worker;
- one execution slot per background worker role;
- SQLAlchemy `pool_size=2`, `max_overflow=1`, `pool_timeout=10`,
  `pool_recycle=1800`, `connect_timeout=5`, and `pool_pre_ping=true`;
- private VPC endpoint and TLS `verify-full`;
- every API/worker process re-resolves the RDS hostname, rejects any non-private
  answer, and passes the approved private `hostaddr` while retaining the
  hostname for TLS identity verification;
- automatic backups with at least seven days retention.

The local/CI PostgreSQL 18 proof establishes schema and database semantics. It
does not prove RDS TLS, private networking, backup, restart, availability, or
capacity.

## 9. Deployment and recovery

The formal runtime and production Compose definitions do not include a
PostgreSQL service, image, volume, or hard dependency. A fresh deployment starts
Redis, setup-capable API, frontend, and proxy; workers begin only after install.
An installed release still follows the governed order: fence writers, migrate
with the release one-off image, start API, start workers, then restore traffic.

A successful fresh install commits
`database_contract=pg18_empty_initialization.v1` together with the exact raw
`runtime-config.json` digest. Subsequent ordinary deployments validate that
evidence and use the candidate release image to prove protected-config loading,
private TLS PostgreSQL 18 reachability, and current Alembic head before stopping
writers. For this explicitly pre-user reset, only the locked host helper may
turn an empty protected tree into a fresh `pending` state. A `complete` state
without the PG18 marker is unsupported and fails closed; the database refactor
does not reinterpret legacy completion evidence or reopen a compatibility path.

The pending first-install cutover stops but preserves the previous local
PostgreSQL container and volume, pins the previous application images and
rollback map, and publishes a root-owned lifecycle marker. Ordinary deployment
and `safe-prune` fail closed until the operator either restores that previous
release while state is still `pending`, or explicitly finalizes after browser
installation and acceptance. Finalization first publishes the permanent
completion sentinel, keeps pruning blocked while cleanup is incomplete, and
then retires the preserved container and rollback pins idempotently.

Before migration begins, the previous release may be restored. After migration
begins, old code must not automatically attach to the new database. Rollback
requires a matched application release, protected configuration, and database
restore point.

The validation RDS must be upgraded to a high-availability edition before the
first real user, paid workload, or irreplaceable business data.

## 10. Non-goals

- no CMS installation or WordPress site creation;
- no Provider, mail, payment, or billing onboarding;
- no ordinary admin editing of the active database target;
- no cloud-vendor provisioning API;
- no PostgreSQL 16 data migration, dual write, or compatibility shim;
- no multi-admin, password login, registration, reset email, or MFA;
- no new workflow engine, scheduler truth, or infrastructure control plane.

## 11. Required verification

- setup-code digest, rate limit, cookie, lock, interrupted retry, and permanent
  close tests;
- admin-key digest, rotation, and session invalidation tests;
- PostgreSQL 18 empty-history migration and idempotent Alembic rerun;
- partial-index, JSON, timestamp, `ON CONFLICT`, `SKIP LOCKED`, payment,
  idempotency, callback, and media-lifecycle semantic tests;
- frontend secret-storage, route-gate, one-time-key, accessibility, and i18n
  tests;
- exact bundle and host runtime contracts proving production does not bundle or
  start PostgreSQL;
- real RDS private/TLS smoke and local WordPress text/media round trip before
  the validation environment is accepted.
