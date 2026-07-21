# ADR-016: Fail Closed At Portal Account And Admin Browser Boundaries

## Status

Accepted

## Date

2026-07-16

## Context

P4 contracts the customer Portal and Cloud Admin without moving WordPress
governance into Cloud. The surface audit found two authorization designs that
violated that goal:

1. Portal site provisioning and WordPress addon connection accepted a client
   `account_id`, checked that the account and principal were independently
   active, and then created the missing membership. A connection request could
   therefore grant the authority it was supposed to require.
2. The Admin browser catch-all proxy forwarded unmatched paths to the internal
   service API and added the internal token. Adding an internal endpoint could
   unintentionally expose it to every valid Admin browser session.

The Portal also retained customer key CRUD routes even though the supported
WordPress addon connection already issues hidden runtime credentials through a
one-time server-side exchange.

There are no production users and no compatibility requirement, so direct
contract deletion is safer and faster than aliases or dual paths.

## Decision

1. Existing active account membership is a precondition for all Portal
   account-scoped writes. The account, principal, and membership must be active,
   and the required action must be explicitly present before any site, key,
   membership, or connection-state write.
2. Portal site/addon connection never creates or repairs membership. Membership
   is created only by the explicit registration or platform-admin membership
   workflow.
3. The Admin browser proxy uses an explicit method, path, backend namespace,
   and existing capability allowlist. Unknown routes fail before the internal
   token is added. Portal-only debug headers are never forwarded by Admin.
4. Customer self-service key CRUD, manual Portal site creation, and unused
   Portal activate/deactivate routes are removed. WordPress addon one-time
   exchange remains the only customer connection credential path. Internal
   service-plane key operations remain available to bounded operators and
   connection automation.
5. Browser proxy and frontend transport errors use the canonical Cloud
   envelope. Internal network exception text is not returned to browsers.

## Alternatives Considered

### Keep client `account_id` and check only at the route

Rejected. A second caller could bypass the route and call the domain service.
The domain write boundary must enforce the membership invariant.

### Let addon connection create membership after validating the email

Rejected. Login identity proves who the caller is, not which account the
caller may join. Connection and authorization are separate operations.

### Maintain a denylist of dangerous Admin paths

Rejected. Denylists become incomplete whenever internal APIs grow. An allowlist
makes exposure an explicit review decision.

### Keep customer key routes hidden from navigation

Rejected. An unlinked API is still an exposed credential surface. The addon
exchange provides the required connection behavior without routine customer
secret handling.

### Preserve redirects and deprecated API responses

Rejected. There are no users or compatibility obligations. Compatibility code
would create the historical burden this refactor is intended to remove.

## Consequences

- Cross-account Portal writes fail closed without revealing whether the target
  account exists or why access failed.
- Adding an internal Cloud endpoint does not expose it through Admin; a new
  browser rule and capability decision are required.
- WordPress users manage site connections, not signing keys.
- Internal operator and addon automation key lifecycle remains intact.
- Frontend consumers must migrate to the canonical envelope and shared client.
- Multi-account Portal selection still requires a later P4 cutover: account
  scope must derive from an authorized selected site or fail closed, never from
  the first membership returned by storage.

## Verification

- Cross-account and missing-action Portal tests assert 403 and zero side
  effects.
- Removed Portal paths assert 404; the removed `POST /portal/v1/sites` method
  asserts 405 because the retained `GET /portal/v1/sites` shares the path.
  Internal key and addon exchange tests remain green.
- Admin proxy contracts assert identity, capability, route, namespace, and
  dangerous-path behavior.
- Shared frontend transport tests cover HTTP errors, HTTP 200 error envelopes,
  non-JSON, invalid JSON/envelopes, network failure, and idempotency.
- P4 closeout runs the gates named in
  `docs/p4-portal-admin-surface-inventory-2026-07-16.md`.
