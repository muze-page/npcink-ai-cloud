# ADR-021: Release-Scoped Runtime Network Authority

## Status

Accepted.

## Date

2026-07-21.

## Context

ADR-020 established one bundled NGINX behind the operator-owned TLS Edge and
used a fresh Compose network with fixed `172.28.0.0/24` addresses. Production,
however, already had the same managed Compose project running on
`10.255.1.0/24`. Replaying the fixed values made the new Compose model disagree
with the network Docker was already using. The first P1-E06 attempt therefore
failed while restoring public traffic even though the application, database,
and Edge topology were otherwise valid.

The real-client trust boundary still needs exact gateway and proxy addresses.
Those addresses cannot come from ambient shell variables, and the proxy may be
intentionally absent while a deployment fences or recreates services. A
rollback must also use the previous release's network authority rather than
the new release's values.

## Decision

The managed Docker network is discovered once for each staged release and
frozen in protected, release-external state:

- `runtime-network.env` records the Compose project, IPv4 subnet, gateway, and
  proxy IPv4 address;
- `nginx.runtime.conf` is rendered from the bundled NGINX source with the
  frozen gateway as its only real-client trust anchor;
- both files live under the root-owned, mode-`0700` per-release state
  directory; the state file and rendered NGINX file are mode `0600`;
- parameterized runtime Compose calls discard ambient network variables and
  reconstruct all four interpolation values from those protected files;
- an existing managed network is retained, while a genuinely fresh network
  defaults to `172.28.0.0/24`, gateway `172.28.0.1`, and proxy
  `172.28.0.10`;
- a temporarily absent proxy retains its frozen address, but a different proxy
  address, multiple proxy endpoints, non-proxy occupation of the frozen
  address, unsafe state, or NGINX drift fails closed;
- ordinary rollback and P1-E06 recovery load and revalidate the previous
  release's own network authority before inspection or recreation.

This supersedes only ADR-020's fixed-address policy. The external TLS Edge,
single bundled NGINX, forwarded-header replacement, and Cloud/WordPress
ownership boundaries remain unchanged.

## Alternatives Considered

### Renumber the existing production network

Rejected because it turns an application release into an infrastructure
renumbering event and can strand healthy containers during rollback.

### Keep addresses only in deployment environment variables

Rejected because subprocesses and one-off Compose calls can lose or override
ambient values. Environment state is not durable release authority.

### Re-discover the proxy address before every Compose call

Rejected because the proxy is intentionally absent during parts of a governed
cutover. Re-selection can silently choose a different free address and break
both NGINX and Gunicorn trust.

### Use Docker DNS names for forwarded-header trust

Rejected because NGINX and Gunicorn require concrete source-address trust
rules at different hops. DNS names do not replace the frozen network identity
contract.

## Consequences

- production can adopt a new exact bundle without renumbering the existing
  managed network;
- every runtime Compose invocation has one durable, auditable network source;
- rollback remains tied to the previous release even after the new release has
  prepared its own state;
- operators must preserve the per-release state directory with the release and
  treat missing or drifted state as a deployment failure;
- fresh environments retain deterministic `172.28.0.0/24` defaults;
- no CMS permissions, WordPress writes, public API, or second control plane are
  introduced.

## Rollback

Before activation, stop the new attempt and use the governed ordinary rollback
or P1-E06 recovery path. Those paths revalidate the previous release's frozen
network state before recreating any service. If that state is unsafe or has
drifted, retain the deploy lock and require operator investigation; do not
guess addresses or reconstruct state from the failed release.

After activation, a later release follows the same rule: its own state governs
forward operation, and the immediately previous release's state governs a
rollback. Legacy non-parameterized releases remain usable only as the explicit
pre-ADR-021 recovery generation.

## References

- [External TLS Edge and a Single Bundled NGINX](020-external-tls-single-bundled-nginx.md)
- [Production GitHub Deploy](../../deploy/PRODUCTION_GITHUB_DEPLOY.md)
- [Production Operations Playbook](../../deploy/OPS_PLAYBOOK.md)
- [Cloud Release Checklist](../../deploy/RELEASE_CHECKLIST.md)
- [Media Runtime Boundary](../media-runtime-boundary-v1.md)
