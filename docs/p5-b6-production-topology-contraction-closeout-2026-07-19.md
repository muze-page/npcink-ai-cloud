# P5-B6 Production Topology Contraction Closeout — 2026-07-19

Status: **engineering acceptance complete** for Cloud implementation revision
`fb58e354`. P5-B7 exact-image scan/bundle evidence, P5-B8 WordPress replay and
restore/matrix evidence, global P5, production migration, and GA remain
incomplete.

## Accepted Outcome

P5-B6 removes avoidable release topology and makes the remaining trust chain
explicit:

```text
client -> operator-owned TLS Edge -> 127.0.0.1:8010 bundled NGINX -> Gunicorn
```

- Caddy, Jaeger, and the OpenTelemetry Collector are absent from both
  production Compose files and the canonical image lock.
- Redis and NGINX are the only Compose-external release images. The image lock
  now has seven production inputs, six application outputs, and two scanner
  images.
- the Cloud bundle owns no public `80/443`; the NGINX ingress is loopback-only;
  the Compose gateway, NGINX, and Gunicorn trust chain is pinned to
  `172.28.0.1 -> 172.28.0.10`;
- the external Edge replaces all forwarded identity/scheme headers, and the
  bundled NGINX reconstructs rather than appends `X-Forwarded-For`;
- ordinary runtime tracing is optional and external. Formal HTTPS smoke still
  requires an explicit OTLP exporter, a trace query URL, and later operator
  proof that a fresh trace is queryable;
- runtime or HTTPS deployment fails before Docker mutation unless the external
  Edge acknowledgement, HTTPS origin, and matching domain contract pass;
- the loader removes Compose orphans and rejects any remaining release-project
  `caddy`, `jaeger`, or `otel-collector` container before public health can
  pass.

This is a release-plane contraction only. Cloud did not gain WordPress
permissions, local ability/workflow truth, approval, audit, or final-write
ownership.

## First-Migration Safety

The binding helper implements a two-stage migration:

1. `--prepare-only` validates the local key mode, certificate/key pair,
   loopback upstream, and inner health; stages files through a random remote
   `0700` directory created under `umask 077`; and runs `nginx -t` without
   installing packages or starting/restarting NGINX.
2. The operator records and stops only Caddy containers matching both the
   exact Compose project and `service=caddy` labels.
3. Activation refuses a still-running project Caddy, starts host NGINX, and
   proves the exact host's HTTPS chain through loopback resolution.
4. An activation error restores the prior certificate, key, site/default
   configuration, and NGINX enabled/running state.
5. The normal loader then replaces the inner bundle and proves retired
   services are absent.

The helper rejects a local private key with any group/other permission before
SSH or SCP. A focused behavior check proved a `0644` key exits with the
expected permission error before network activity. Independent review found
the original migration-order and remote-key permission P1 findings closed,
with no remaining P0/P1/P2 blocker.

## Verification Evidence

| Gate | Result |
| --- | --- |
| focused deployment/image/bundle contracts | `62 passed` |
| focused tracing/service tests | `12 passed` |
| `pnpm run check:fast` contracts | `340 passed, 29 skipped` |
| `pnpm run check:fast` domain | `611 passed, 3 skipped` |
| `pnpm run check:seam` API | `889 passed` |
| `pnpm run check:seam` perimeter | `9 passed` |
| standalone `pnpm run check:perimeter` | `9 passed` |
| `pnpm run check:anti-drift` | passed |
| `pnpm run lint` | Ruff passed; mypy passed for 232 source files |
| frontend type-check and lint | passed |
| release-policy check | passed |
| production/runtime Compose config | passed |
| bundled and rendered external NGINX `nginx -t` | passed |
| image-lock offline verification | passed: 7 inputs, 6 outputs, 2 scanners |
| trusted/untrusted client-IP topology fixture | passed; trusted Edge values remained distinct and an untrusted spoof was rejected |
| shell syntax and `git diff --check` | passed |
| independent P5-B6 review and re-review | no open P0/P1/P2 blocker |

The full-gate Docker run used an isolated Compose project and non-conflicting
temporary host ports. Its containers, network, and volumes were removed, and
the temporary Compose edit was reverted. The existing development project was
not stopped or recreated.

The 29 clean-repository exact-bundle cases intentionally skipped while the B6
implementation was uncommitted. They are not counted as bundle evidence. P5-B7
must rerun them from a clean committed tree and complete the real platform
image scan, exact bundle construction, verification, and replay.

## Remaining Boundaries

P5-B6 does not provide:

- a production deployment or production Edge cutover;
- a disposable Linux SSH-host execution of `systemctl` rollback and the real
  Caddy-to-NGINX port handoff;
- certificate-renewal, external WAF, DNS, or trace-backend operator evidence;
- an accepted exception for the three upstream Python 3.14.6 High CVEs;
- a clean-tree exact bundle, current WordPress text/media replay, restore
  rehearsal, six-repository matrix, or final P0-P5 audit.

No production action is authorized by this closeout. The next engineering
batch is P5-B7 exact-image and bundle closure. It may use a CVE allowlist only
after a named human explicitly accepts the exact owner, scope, expiry,
evidence, and rollback; otherwise the real CVE failure remains release
blocking.
