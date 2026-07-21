# P5-B2 Security Hardening Closeout

Status: engineering batch complete; production cutover, production approval,
and global P5 release closure remain incomplete.

Date: 2026-07-17.

## Outcome

P5-B2 closes the two release blockers identified by the P5-A audit:

1. Pillow is raised to `12.3.0`, the default and Zilliz locked dependency
   variants audit with no known vulnerabilities, and the audit is a blocking
   backend CI prerequisite.
2. Five persisted runtime-data ciphertext types now use a dedicated,
   purpose-bound `rde.v1` domain instead of Admin, Portal, or internal-auth
   roots. Normal runtime has no historical-key or raw-token reader.

This is a direct security cutover. It does not retain aliases, fallback roots,
dual reads, dual writes, or version negotiation. The offline maintenance tool
is retained only for an explicit stopped-writer cutover or later controlled
rekey.

## Dependency And Supply-Chain Changes

- `Pillow>=12.3,<13.0` resolves to `12.3.0` in `uv.lock`.
- The lock now correctly keeps `pymilvus` under the optional `zilliz` extra
  instead of the default dependency set.
- `scripts/check-python-dependency-audit.sh` verifies the lock, exports hashed
  default and Zilliz requirements, and runs pinned `pip-audit 2.10.1` against
  both.
- Cloud CI requires that audit before the backend aggregate gate can pass.
- Production deployment also requires the existing secret-scan job to pass.
- The one reviewed Alipay private-key fixture finding is ignored by one exact
  fingerprint; no broad secret rule is disabled.
- Production-image smoke now checks Pillow's supported range and the expected
  presence or absence of `pymilvus` in both image variants.

The Docker build still resolves allowed dependency ranges rather than
installing directly from `uv.lock`. The image smoke proves the security-critical
Pillow floor and extra composition, not a complete image CVE assessment. An
actual container-image scan remains a P5-B5 release gate.

## Runtime-Data Encryption Changes

The active envelope is `rde.v1.<key_id>.<fernet_token>`. It covers exactly:

| Kind | Storage location |
| --- | --- |
| Site API signing secret | `site_api_keys.signing_secret_ciphertext` |
| Terminal callback secret | `sites.metadata_json.runtime_callbacks.terminal.secret_ciphertext` |
| Addon connection payload | `portal_oauth_states.metadata_json.payload_ciphertext` |
| Portal idempotency response | `portal_mutation_idempotency_receipts.response_body_ciphertext` |
| Runtime execution input | `run_records.execution_input_ciphertext` |

Provider connections and service settings remain under their existing
service-settings encryption domain and are explicitly excluded.

Outside development and test, the runtime-data root and key ID are required,
and configured auth/encryption domains must be pairwise distinct. Runtime
decrypts only the active envelope, key ID, root, and purpose. Raw Fernet, old
RDE, wrong-purpose, malformed, and unknown-version input fail closed.

`python -m app.dev.reencrypt_runtime_data` provides count-only
`inventory`, `dry-run`, single-transaction `apply`, and active-key-only
`verify` phases. It accepts raw legacy rows for the first cutover and only
explicitly named old RDE key IDs for a future rekey. A damaged row aborts the
whole apply. Repeating a successful apply performs no writes.

## Deployment Boundary And Recovery

- The runtime-data secret and key ID reach `api`, `worker`,
  `callback-worker`, and `ops-worker` only.
- Development and production frontends no longer inherit complete backend env
  files; they receive the explicitly allowlisted internal token required by the
  current server-side BFF.
- The development Compose wrapper layers `.env` and then `.env.local` for
  interpolation, preserving local overrides without exposing unrelated secrets
  to the frontend.
- The production Compose proxy binds to loopback.
- The staged-release runbook copies a protected `.env.deploy` with mode `0600`
  before any Compose command, fences all four writers, verifies a matched
  backup/code/key recovery point, and runs maintenance inside the new API
  image.
- Rollback restores the matched old database, application revision, and key as
  one unit. Runtime does not gain an old-key fallback.

No production database, secret, service, release symlink, or external host was
changed in this engineering batch.

## Verification Evidence

| Gate | Result |
| --- | --- |
| Locked default dependency audit | passed; `0` known vulnerabilities |
| Locked Zilliz dependency audit | passed; `0` known vulnerabilities |
| `uv 0.11.29 lock --check` | passed |
| Production default image smoke | passed; Pillow `12.3.0`, no `pymilvus` |
| Production Zilliz image smoke | passed; Pillow `12.3.0`, `pymilvus` present |
| Focused media/API/worker tests | `324 passed, 1 skipped` |
| Representative media corpus | `5` accepted, `2` expected rejects |
| Merged encryption/deploy/dependency contracts | `47 passed, 1 skipped` |
| PostgreSQL 16 full-schema raw-to-RDE rehearsal | `5/5` migrated, `5/5` verified, repeat apply `0` |
| PostgreSQL 16 old-RDE-to-new-RDE rehearsal | `5/5` inventoried, migrated, and verified |
| PostgreSQL 16 corrupt-row rehearsal | failed closed; all `5/5` ciphertexts unchanged |
| Provider/service-setting sentinels | unchanged after migration |
| Deploy contract and release-policy checks | passed |
| `pnpm run check:fast` | contract `177 passed, 1 skipped`; domain `602 passed, 3 skipped` |
| `pnpm run check:seam` | API `746 passed`; perimeter `9 passed` |
| `pnpm run check:anti-drift` | passed |
| `pnpm run lint` | Ruff passed; mypy passed for `231` source files |
| Development and production Compose config | passed |
| Secret scan with reviewed baseline and exact fixture ignore | passed |
| Independent review | no actionable P0-P3 finding |

The PostgreSQL rehearsal created three disposable databases on PostgreSQL 16,
upgraded each through Alembic head `20260717_0068`, ran the three scenarios,
and removed the container afterward. It did not use or mutate production data.

## Explicit Non-goals And Remaining Work

This batch did not:

- deploy to production or execute the production ciphertext cutover;
- prove a production backup/restore or rotate live credentials;
- perform a penetration test, complete container-image CVE scan, or
  online-provider credential validation;
- close the P5-A JWT required-claim, global sensitive-log, lock-synchronization,
  or Dependabot follow-ups;
- complete current WordPress text acceptance, load/soak evidence, the exact
  release-bundle replay, or the final clean cross-repository matrix.

Those items remain in P5-B3 through P5-B5. This record closes P5-B2 engineering
only and must not be cited as production approval or global P5 completion.
