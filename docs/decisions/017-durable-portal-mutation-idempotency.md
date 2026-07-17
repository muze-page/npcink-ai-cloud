# ADR-017: Durable Portal Mutation Idempotency

## Status

Accepted.

## Date

2026-07-17.

## Context

Authenticated Portal mutations already declared `Idempotency-Key` as a
required request header, and the shared frontend client already generated the
header for writes. The backend Portal bearer path ignored
`require_idempotency`, however, and `_portal_write_guard` did not reserve or
replay anything. A browser, proxy, or caller retry could therefore create a
second payment order, support message, attachment, or other commercial side
effect.

The project is pre-GA and has no compatibility burden. This is a direct
contract cutover rather than a dual-path migration.

## Decision

Use a durable PostgreSQL receipt for each authenticated Portal mutation that
declares `require_idempotency=True`.

The receipt contract is:

- scope is the canonical Cloud `principal_id` plus the caller-supplied
  `Idempotency-Key`;
- the key is required and must contain 1-128 safe characters;
- the request fingerprint covers the HTTP method, path, query, authenticated
  selected `site_id`, and normalized request body, so one principal cannot
  replay a response across two account/site contexts;
- request bodies are not stored in the receipt; only the SHA-256 fingerprint
  is retained;
- the first request atomically claims a short processing lease before the
  business mutation runs;
- an exact request arriving while that lease is active fails with
  `409 portal.idempotency_in_progress`;
- reusing the key for a different request fails with
  `409 portal.idempotency_conflict`;
- once the response is durably recorded, an exact retry receives the original
  HTTP status and body with `Idempotency-Replayed: true`;
- an expired processing lease is not automatically reclaimed: because the
  business transaction and HTTP receipt use separate database transactions,
  the original result is indeterminate and the same key fails closed with
  `409 portal.idempotency_indeterminate` until an operator reconciles it;
- completed receipts remain replayable for the configured receipt TTL, which
  defaults to 24 hours.

Response capture happens at the Portal HTTP boundary before the response is
released to the caller. Each participating route has one small replay
checkpoint after its current authorization checks and before its business
side effect; response persistence remains centralized in middleware.

## Security And Ownership Boundaries

The receipt is security and delivery evidence for Cloud-owned Portal writes.
It does not authorize a request, replace account/site authorization, own
WordPress content, or create a second CMS control plane. Authentication,
same-origin enforcement, selected-site authorization, and the business
transaction remain mandatory on the first execution.

PostgreSQL is the canonical receipt store. Redis remains optional transient
runtime support and is not used as idempotency truth. Exact response bodies are
encrypted at rest with a purpose-separated Cloud key before storage. They may
contain customer-authored response projections and, for addon connection
issuance, a short-lived one-time delivery URL; the table must therefore be
handled as sensitive delivery evidence. Provider secrets, session tokens, and
WordPress credentials are not deliberately projected into the receipt.

The receipt does not replace current authorization. A completed response is
replayed only after the route revalidates the principal's current account,
site, action, or support-request access.

Unauthenticated login-code, registration, session selection, logout, addon
exchange, and public runtime contracts retain their existing purpose-specific
replay behavior. This ADR does not silently broaden the protected mutation
set; a route joins this contract by explicitly declaring
`require_idempotency=True`.

## Alternatives Considered

### Reject every duplicate key without replaying the response

This prevents an obvious second write but leaves a caller unable to distinguish
a completed first request from a lost response. It is insufficient for payment
and support mutations.

### Keep receipts only in process memory or Redis

This loses the guarantee across processes, restarts, and Redis eviction, and
would make a transient component the source of truth.

### Add idempotency separately inside every commercial service method

Several services already have narrower dedupe rules, but duplicating transport
receipt logic in each route/service would create inconsistent error and replay
semantics. Domain-specific unique constraints remain defense in depth; the
Portal boundary owns the request/response contract.

### Add automatic frontend retries

Automatic retries are not required to close the backend race and would add a
new failure policy. The shared client continues to support explicit key reuse;
retry policy can be considered independently.

## Consequences

- callers can safely retry a mutation whose response was durably recorded;
- an in-flight duplicate is rejected, while a request stranded beyond its
  lease fails closed for reconciliation instead of risking a second side
  effect;
- key reuse across routes or payloads fails closed instead of applying an
  unrelated mutation;
- concurrent duplicates permit one active business execution;
- the database gains a bounded receipt record and indexed expiry data;
- replay returns the original envelope, including its original trace evidence,
  rather than fabricating a second success;
- endpoints that do not opt into `require_idempotency=True` are deliberately
  unchanged and must be reviewed explicitly if their ownership changes.

## Verification

The acceptance suite must cover missing and invalid keys, exact replay,
encrypted response storage, same-key conflict, principal isolation, active
processing leases, indeterminate expired leases, concurrent duplicate
submission, migration upgrade/downgrade, and unchanged pass-through behavior
for non-participating Portal routes.

P4 closeout additionally runs the repository Portal tests, frontend transport
tests, `check:fast`, `check:seam`, `check:perimeter`, `check:anti-drift`, and
lint/type gates.
