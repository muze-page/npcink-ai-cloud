# ADR-020: External TLS Edge and a Single Bundled NGINX

## Status

Accepted.

## Date

2026-07-19.

## Context

The production bundle previously carried two HTTP perimeter layers: Caddy
terminated public TLS and forwarded to NGINX, while NGINX enforced the Cloud
route, upload, download, and internal-path policy. The same bundle also carried
an OpenTelemetry Collector and Jaeger. This duplicated ingress responsibility,
increased the locked-image and CVE surface, and made the exact release bundle
own infrastructure that production operators may already provide.

Cloud still needs one repository-owned HTTP policy layer. In particular, the
media runtime depends on exact NGINX body-size, timeout, rate, connection,
streaming, and sanitized logging controls. It does not need to own public TLS,
DNS, WAF, or the production trace backend.

## Decision

Production uses this request chain:

```text
client -> operator-owned TLS Edge -> bundled NGINX -> Gunicorn
```

The following rules are part of the release contract:

- the external Edge owns public `80/443`, certificates, TLS policy, public DNS,
  optional WAF, and source restrictions;
- the exact Cloud bundle publishes no public `80/443` listener;
- the bundled NGINX remains the only repository-owned HTTP policy layer and is
  pinned to `172.28.0.10` on `172.28.0.0/24`;
- the Compose network gateway is pinned to `172.28.0.1`;
- the external Edge connects to NGINX through the operator-controlled host
  ingress and replaces, rather than appends to, inbound `X-Real-IP`,
  `X-Forwarded-For`, `X-Forwarded-Proto`, `X-Forwarded-Host`, and
  `X-Forwarded-Port` values;
- NGINX accepts the real client address only from the pinned network gateway,
  then forwards normalized headers to Gunicorn;
- Gunicorn accepts forwarded headers only from NGINX at `172.28.0.10`;
- the only bundled external images are Redis and NGINX. Caddy, Jaeger, and the
  OpenTelemetry Collector are retired from both Compose and the image lock;
- OTLP export is optional for ordinary runtime operation and points to an
  operator-owned endpoint when configured. A formal release still requires
  both an exporter endpoint and a query URL, plus evidence that a fresh trace
  is queryable;
- the remote loader starts the exact current service set with orphan removal
  and fails verification if a retired `caddy`, `jaeger`, or `otel-collector`
  container remains in the release project.

The exact-bundle smoke may bind NGINX to loopback and use plain HTTP. That is a
local artifact-replay exception only; it is not a supported production public
origin and does not weaken the external TLS requirement.

This changes deployment topology only. Cloud remains the hosted runtime/detail
layer. It does not gain CMS permissions, approval, audit, registry, or direct
WordPress write ownership.

## Migration

Before deploying the first release with this topology:

1. Record the previous release and database recovery point, and retain the
   previous image bundle until the verification window closes.
2. Prepare the host Edge files and pass `nginx -t` without starting host NGINX
   while the retired Caddy still serves public traffic.
3. Record and stop only the old release project's labeled Caddy containers,
   then activate host NGINX and prove the exact host's HTTPS-to-loopback chain.
   Activation refuses a still-running project Caddy and restores the previous
   host NGINX files and service state on failure.
4. Deploy the new exact bundle and let the loader remove Compose orphans.
5. Verify no release-project containers remain for Caddy, Jaeger, or the
   OpenTelemetry Collector.
6. Verify forwarded-header replacement, public HTTPS, `/health/live`,
   authenticated readiness, media upload
   and pull limits, signed runtime execution, and trace export/query evidence.

Do not leave the retired Caddy listener on public `80/443` during cutover. A
second active edge can make client-IP and scheme evidence ambiguous even when
requests appear to succeed.

## Alternatives Considered

### Keep Caddy in front of NGINX

Rejected because NGINX already owns the application perimeter contract and the
operator-owned Edge must already own production TLS. A second bundled edge adds
images, configuration, and trust hops without adding a Cloud-owned capability.

### Expose Gunicorn directly behind the external Edge

Rejected because it would remove the exact route-specific media, internal-path,
rate, connection, timeout, and logging controls implemented in NGINX.

### Keep the bundled Collector and Jaeger as defaults

Rejected because production trace storage and query are operator infrastructure.
Cloud should export evidence to that infrastructure, not ship a second default
observability stack.

## Consequences

- The production bundle has fewer privileged listeners, images, CVE feeds, and
  long-running services.
- The real-client trust chain is explicit and testable at each hop.
- An operator must provision the TLS Edge before production traffic can be
  restored.
- OTLP is no longer available merely because the Cloud bundle started; formal
  release evidence must name and query the external sink.
- Local exact-bundle smoke remains fast and self-contained on loopback HTTP.

## Rollback

If activation fails before the loader runs, stop host NGINX before restarting
only the recorded old Caddy containers. If the loader has started, stop the new
project and host NGINX before restoring the matched previous Compose release,
its database recovery point when required, and its Caddy route. Verify that
only one public TLS path is active. Do not restore Caddy beside host NGINX, and
do not keep retired observability containers attached to the current release
project.

## References

- [Production GitHub Deploy](../../deploy/PRODUCTION_GITHUB_DEPLOY.md)
- [Production Operations Playbook](../../deploy/OPS_PLAYBOOK.md)
- [Cloud Release Checklist](../../deploy/RELEASE_CHECKLIST.md)
- [Media Runtime Boundary](../media-runtime-boundary-v1.md)
- [Streamed Signed Media Ingress](006-streamed-signed-media-ingress.md)
