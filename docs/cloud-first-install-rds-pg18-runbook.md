# Cloud First Install with Alibaba RDS PostgreSQL 18

Status: operator runbook for the validation environment.

This runbook implements
[Cloud First Install Contract v1](cloud-first-install-contract-v1.md). It does
not authorize a production cutover while any independent release gate is red.

## 1. Preconditions

- target release commit and exact bundle are known;
- the exact release canonical CVE allowlist no longer contains the three
  blocked Python 3.14.6 exceptions and its fresh image scan is green; the
  deploy helper enforces this before any first-install host mutation;
- Alibaba RDS PostgreSQL 18 Basic `pg.n2e.1c.1m` exists in the same region and
  VPC as the Cloud host;
- only the private RDS endpoint is enabled for the Cloud host security group;
- an empty application database and least-privilege application account exist;
- the current Alibaba RDS CA chain has been downloaded from the authoritative
  console or documentation;
- `NPCINK_CLOUD_BASE_URL`, browser origin allowlist, trusted host allowlist,
  Redis, edge, and non-secret deploy inputs are ready;
- database passwords, runtime roots, setup codes, and admin keys are absent from
  `.env.deploy`, shell history, command arguments, tickets, and chat logs.

The Basic instance is validation-only. Upgrade to a high-availability edition
before the first real user, paid workload, or irreplaceable data.

## 2. Local proof

Run the disposable schema proof:

```bash
pnpm run check:pg18-proof
```

This proves an empty PostgreSQL 18 migration and idempotent replay without TLS.
It is not evidence for RDS private DNS, `verify-full`, backup, failover, restart,
or capacity.

## 3. First deployment

Use the governed deployment path from the approved release commit:

```bash
source deploy/workspace-target.env.sh
pnpm run deploy:ssh
```

On a host without installation state, the deploy helper creates the protected
shared configuration directory and an intentionally undisclosed setup-code
digest. CI and deployment stdout never receive a usable `nca_setup_...` value.
After deployment, issue the usable code from an interactive SSH terminal:

```bash
ssh -t root@<cloud-host> \
  '/opt/npcink-ai-cloud/current/deploy/setup-code-rotate.sh'
```

Save the displayed value in the operator password manager immediately. The
host retains only its SHA-256 digest. The helper rejects non-TTY output, so do
not wrap it in command substitution, CI, or an SSH capture pipeline.

This path is accepted only when the protected tree also has no runtime config,
RDS CA, or frontend token projection. A missing state file beside any of those
artifacts is a recovery incident and fails closed instead of reopening Setup.

The first-deploy path starts Redis, the setup-capable API, frontend, and proxy.
Worker containers run only the install-state wait wrapper and do not construct
database services.

## 4. Browser installation

Open `<Cloud public origin>/setup` and complete the four steps:

1. exchange the one-time setup code;
2. confirm Cloud name and the exact HTTPS public origin;
3. enter the private RDS host, port, database, user, password, and CA chain;
4. test, initialize, and save the one-time `nca_admin_...` key.

The public origin must exactly match the bootstrap browser-origin allowlist;
change the deploy input before installation if the hostname is wrong. The
installer rejects non-Alibaba RDS hostnames, any public/loopback/link-local
resolution, PostgreSQL versions other than 18, non-verified TLS, non-empty or
foreign databases, and insufficient DDL permissions. Never substitute the local
proof certificate or disable `verify-full` to pass this step.

After success:

- save the admin key in the operator password manager;
- confirm protected `install-state.json` records
  `database_contract=pg18_empty_initialization.v1` and the exact
  `runtime-config.json` SHA-256;
- confirm `/setup` returns 404 and `/setup/v1/state` returns only `complete`;
- confirm internal readiness and all three workers become healthy;
- log in through `/admin/login` with the saved key;
- do not copy the key into `.env.deploy`.

## 5. Lost credentials

Before installation completes, rotate a lost setup code on the host with the
active release from an interactive terminal:

```bash
ssh -t root@<cloud-host> \
  '/opt/npcink-ai-cloud/current/deploy/setup-code-rotate.sh'
```

After installation, rotate a lost or exposed admin key with:

```bash
ssh -t root@<cloud-host> \
  '/opt/npcink-ai-cloud/current/deploy/admin-key-rotate.sh'
```

The latter rotates both the admin-key digest and admin-session signing root,
then restarts the API. Old keys and cookies become invalid together. There is no
public setup reset, password recovery, or key-display endpoint.

## 6. Acceptance

Before accepting the validation environment:

- run the repository fast, seam, perimeter, anti-drift, release-policy, exact
  bundle, and cross-repository matrix gates;
- prove the real RDS connection uses its private endpoint and TLS
  `verify-full` with the submitted CA;
- complete WordPress text and image round trips from
  `https://magick-ai.local/` without Cloud writing CMS content directly;
- observe the host and RDS for 24 to 72 hours;
- run one RDS backup restore drill to a separate validation target;
- keep the old PostgreSQL 16 volume offline for seven days, then delete it only
  after the evidence and rollback decision are recorded.

The first deployment deliberately preserves the retired local PostgreSQL
container, rollback image tags, previous release, and protected rollback map.
`safe-prune` fails closed while this lifecycle is pending. After browser setup,
worker readiness, and the acceptance checks above pass, finalize explicitly:

```bash
ssh root@<cloud-host> \
  '/opt/npcink-ai-cloud/current/deploy/first-install-finalize.sh'
```

Finalize atomically creates the root-owned permanent installation sentinel,
removes any setup-auth residue, retires the old local PostgreSQL container, and
only then releases rollback assets for later pruning. Do not run it merely
because the browser reported success; it is the operator acceptance boundary.
The permanent sentinel is `/opt/npcink-ai-cloud/.installation-complete`; the
protected pending/finalizing marker remains until every cleanup step succeeds.

## 7. Rollback

While installation remains `pending`, restore the preserved previous release
with:

```bash
ssh root@<cloud-host> \
  '/opt/npcink-ai-cloud/current/deploy/first-install-rollback.sh'
```

The helper refuses rollback after installation becomes `complete`. Before RDS migration starts, the previous release may be restored. Once a
migration starts, never automatically attach old code to the new database.
Rollback requires the matched old release, protected configuration, and database
restore point. A completed installation with a database outage remains
`complete`; investigate and recover the database instead of reopening Setup.
