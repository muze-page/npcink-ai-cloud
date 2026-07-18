# ADR-019: Dedicated Runtime-Data Encryption Domain

## Status

Accepted.

## Date

2026-07-17.

## Context

Five kinds of persisted Cloud runtime data were encrypted through roots that
also authenticated Admin or Portal sessions or internal service requests:

- site API signing secrets;
- terminal callback secrets in site metadata;
- WordPress Addon connection payloads;
- Portal mutation-idempotency response bodies;
- runtime execution inputs.

That coupling enlarged the impact of one compromised credential and made an
ordinary session-key rotation capable of stranding durable ciphertext.
Provider-connection and service-setting credentials already use the dedicated
service-settings domain and are not part of this decision.

The project has no production users and does not need a permanent compatibility
reader. It does need a controlled cutover for existing development or
operator-owned rows and a reusable, explicit rekey procedure for later key
rotation.

## Decision

Introduce one dedicated runtime-data encryption domain:

- `NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET` is the root secret;
- `NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID` is its non-secret operator
  identifier;
- both are required outside development and test;
- every configured authentication or encryption root must be distinct outside
  development and test.

New ciphertext uses the envelope
`rde.v1.<key_id>.<fernet_token>`. The Fernet key remains purpose-derived, so a
token for one of the five data kinds cannot be replayed as another kind. Normal
runtime code accepts only the active envelope version, key ID, root, and
purpose. It does not read raw historical Fernet tokens, old RDE keys, Admin
session roots, Portal JWT roots, or internal-auth roots.

Keep historical reads in one offline maintenance module only. Its four phases
are:

1. `inventory`, which emits counts and row identifiers without decrypting;
2. `dry-run`, which decrypts every expected historical row and verifies the new
   envelope round trip without writing;
3. `apply`, which locks the relevant rows and updates the complete set in one
   database transaction;
4. `verify`, which requires every non-empty row to use and decrypt with the
   active key.

The first cutover supports raw historical Fernet ciphertext. A later controlled
rekey may explicitly allow named old `rde.v1` key IDs and pair each ID with one
old root. Unknown versions and key IDs fail closed. Reports never include
plaintext, roots, tokens, or metadata payloads.

Run `apply` only in a maintenance window after fencing `api`, `worker`,
`callback-worker`, and `ops-worker`. Retain a checksum-verified, restore-tested
database backup together with the matching old application revision and old
key. Execute the tool from the new staged release image, verify before starting
writers, and remove temporary old-key material after the rollback-evidence
window. Retain the generic migration-only tool for future controlled rekeys;
it is not a runtime compatibility path.

The frontend receives only the existing explicit internal token needed by its
server-side BFF. Runtime-data encryption, Admin, Portal, database, provider,
and service-setting secrets remain backend-only.

## Alternatives Considered

### Continue the Admin-session fallback chain

Rejected because it preserves the compromise domain and makes session rotation
unsafe for persisted runtime data.

### Add permanent dual-read or lazy re-encryption

Rejected because there are no production users to protect with compatibility.
It would keep old roots online, complicate every read, and make completion
dependent on whether all historical rows happen to be accessed.

### Re-encrypt provider and service-setting credentials in the same batch

Rejected because those records already have a separate owner and encryption
domain. Expanding the migration would increase rollback risk without closing
the runtime-data problem.

### Move secrets or migration truth into a CMS connector

Rejected because these ciphertexts belong to the hosted runtime and Portal
service plane. WordPress remains the local permission, review, apply, audit,
and final-write owner.

## Consequences

- Session, internal-auth, service-setting, and persisted-runtime compromise
  domains are separated.
- Every ordinary deployment must preserve the runtime-data secret and key ID.
- A key change is a coordinated data migration, not a configuration-only
  restart.
- Existing rows are unreadable by the new runtime until the maintenance
  cutover completes; this is an intentional direct cutover, not a compatibility
  regression.
- The five storage locations are now explicitly inventoried and covered by one
  transaction and one verification contract.
- Future CMS adapters can reuse the Cloud runtime without inheriting a
  WordPress-specific key store or creating a second CMS control plane.

## Rollback

Before new-key writes begin, stop the four writers and restore the matched old
database backup, old application revision, and old key together. Restoring only
code, only the database, or only an environment value is invalid.

After new-key writes begin, either run a separately verified reverse
re-encryption or restore the complete old recovery point with an explicitly
accepted loss of post-cutover writes. Normal runtime never gains an old-key
fallback for rollback.

## References

- [P5-B2 Security Hardening Closeout](../p5-b2-security-hardening-2026-07-17.md)
- [Production Operations Playbook](../../deploy/OPS_PLAYBOOK.md)
- [Production Release Policy](../cloud-production-release-policy-v1.md)
- [WordPress-first Cloud Runtime Refactor](004-wordpress-first-cloud-runtime-refactor.md)
