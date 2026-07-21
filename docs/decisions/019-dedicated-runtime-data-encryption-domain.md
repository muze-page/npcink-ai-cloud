# ADR-019: Dedicated Runtime and Service-Secret Encryption Domains

## Status

Accepted.

## Date

2026-07-20.

## Context

Persisted Cloud secrets must not share authentication roots or an ambiguous
ciphertext format. Runtime data had already gained an `rde.v1` envelope, but
its Fernet key was derived with a direct SHA-256 construction. Provider
connections and service settings used another root but still stored raw Fernet
tokens derived by the same construction, with no version or key identifier.

The persisted runtime set includes:

- site API signing secrets;
- terminal callback secrets in site metadata;
- WordPress Addon connection payloads;
- Portal mutation-idempotency response bodies;
- runtime execution inputs.

The service-secret set includes provider-connection credentials and service
setting credentials. These sets have different roots and remain separate from
Admin sessions, Portal JWTs, internal authentication, and every other
credential domain.

The project has no production users and does not need permanent compatibility
readers. Existing operator-owned rows still require an explicit, fenced
maintenance cutover rather than silent runtime fallback.

## Decision

### Root and key identifiers

Use two dedicated domains:

- runtime data: `NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET` and
  `NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID`;
- provider/service settings: `NPCINK_CLOUD_SERVICE_SETTINGS_SECRET` and
  `NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID`.

Both roots and both key identifiers are required in production-like
environments. A root is the canonical, padded URL-safe Base64 encoding of
exactly 32 random bytes. A key identifier must match
`[A-Za-z0-9_-]{1,64}`. Production configuration validates these properties,
and every runtime Fernet builder repeats the root and identifier validation so
an invalid value fails closed even in a development or maintenance process.

Every configured authentication or encryption root must remain distinct in a
production-like environment.

### Ciphertext envelopes

New writes use only these formats:

- runtime data: `rde.v1.<key_id>.<fernet_token>`;
- provider and service settings: `sse.v1.<key_id>.<fernet_token>`.

The `rde` and `sse` families are deliberately separate. Provider connections
and service settings share the `sse` family and root, but use different KDF
purposes. Normal decryptors require the exact expected family, version, active
key ID, purpose, and root. They reject raw Fernet, another family or version,
an unknown key ID, malformed envelope syntax, and tokens created for another
purpose.

### HKDF-SHA256 contract

Fernet keys are derived with HKDF-SHA256 using this frozen byte contract:

- input key material: the 32 bytes decoded from the configured root;
- output length: 32 bytes, then URL-safe Base64 encoded for Fernet;
- salt: `npcink-ai-cloud:fernet-envelope-kdf:v1`;
- info: the following ASCII byte strings joined by one NUL byte, in order:
  - `npcink-ai-cloud:fernet-envelope-context:v1`;
  - `family=<family>`;
  - `version=<version>`;
  - `purpose=<purpose>`;
  - `key_id=<key_id>`.

Binding family, version, purpose, and key ID prevents a token from being
replayed across storage families, semantic purposes, or rotations even when a
root is accidentally reused. Direct SHA-256 derivation is not permitted in
`app/core/secrets.py`.

### No compatibility reads in normal runtime

Normal application helpers expose only the active envelope contracts. They do
not read raw historical Fernet, direct-SHA ciphertext, old `rde`/`sse` keys, or
session/authentication roots. There is no dual-read, lazy re-encryption, or
fallback chain.

Any historical decryptor belongs only in an explicit offline maintenance
module. It must require named old key material, expose no plaintext or key
material in reports, and run through four phases:

1. `inventory`, which emits counts and row identifiers without decrypting
   legacy rows or receiving an old root, while validating every already-current
   envelope with the target root;
2. `dry-run`, which decrypts every expected historical row and verifies the new
   envelope round trip without writing;
3. `apply`, which locks the relevant rows and updates the complete set in one
   database transaction;
4. `verify`, which requires every non-empty row to use and decrypt with the
   active key.

Legacy direct-SHA code may exist only in that maintenance boundary and must not
be imported by normal request, worker, provider, or service-setting paths.

Run `apply` only in a maintenance window after fencing all writers. Retain a
checksum-verified, independently restore-tested database backup together with
the matching old application revision and both old roots. Execute the tools
from the new staged release image, verify before starting writers, and remove
temporary old-root material after the rollback-evidence window. The Runtime
Data tool already supports an explicitly approved future `rde.v1` rotation.
The Service Settings tool in this decision supports only the first raw-Fernet
to `sse.v1` cutover; a later `sse.v1` rotation requires a separately designed
and approved old-key-ID contract.

The frontend receives only the existing explicit internal token needed by its
server-side BFF. Runtime-data encryption, service-setting encryption, Admin,
Portal, database, and provider secrets remain backend-only.

## Alternatives Considered

### Keep direct SHA-256 derivation

Rejected because it is an ad-hoc KDF without an explicit salt/context contract.
HKDF provides a standard extract-and-expand construction and makes domain,
purpose, version, and rotation isolation explicit.

### Keep raw Fernet for provider and service settings

Rejected because an unversioned token cannot identify its encryption family or
key rotation and cannot fail closed before attempting decryption.

### Continue an Admin-session fallback chain

Rejected because it preserves the compromise domain and makes session rotation
unsafe for persisted runtime data.

### Add permanent dual-read or lazy re-encryption

Rejected because there are no production users to protect with compatibility.
It would keep old roots online, complicate every read, and make completion
dependent on whether all historical rows happen to be accessed.

### Merge runtime and service secrets into one root

Rejected because provider/service credentials and runtime data have different
owners, rotation events, and exposure paths. A single root would enlarge the
impact of either domain being compromised.

### Move secrets or migration truth into a CMS connector

Rejected because these ciphertexts belong to the hosted runtime and service
plane. WordPress remains the local permission, review, apply, audit, and final
write owner.

## Consequences

- Session, internal-auth, service-setting, and persisted-runtime compromise
  domains remain separated.
- New provider, service-setting, and runtime writes are self-identifying by
  family, version, and active key ID.
- A root or key-ID change is a coordinated data migration, not a
  configuration-only restart.
- Existing rows are unreadable by the new runtime until the maintenance
  cutover completes; this is an intentional direct cutover, not a compatibility
  regression.
- Invalid legacy root material is rejected before Fernet construction.
- Future CMS adapters can reuse the Cloud runtime without inheriting a
  WordPress-specific key store or creating a second CMS control plane.

## Rollback

Before new-key writes begin, stop all writers and restore the matched old
database backup, old application revision, and old keys together. Restoring
only code, only the database, or only environment values is invalid.

After new-key writes begin, either run a separately verified reverse
re-encryption or restore the complete old recovery point with an explicitly
accepted loss of post-cutover writes. Normal runtime never gains an old-key
fallback for rollback.

## References

- [P5-B2 Security Hardening Closeout](../p5-b2-security-hardening-2026-07-17.md)
- [Production Operations Playbook](../../deploy/OPS_PLAYBOOK.md)
- [Production Release Policy](../cloud-production-release-policy-v1.md)
- [WordPress-first Cloud Runtime Refactor](004-wordpress-first-cloud-runtime-refactor.md)
