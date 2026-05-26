# Projection Drill Evidence 2026-04-15

Status: `completed`  
Environment: `mini preview`  
Base URL: `http://100.102.170.79:8010`

Canonical runbook references:

- `cloud/deploy/RELEASE_CHECKLIST.md`
- `cloud/deploy/OPS_PLAYBOOK.md`

## Scope

This drill validates the projection-first closeout for the addon read surfaces:

- signed `GET /v1/addon/dashboard`
- signed `GET /v1/addon/providers/release-summary`

It also confirms that the mini preview environment can be rebuilt through
`scripts/remote-preview-mini.sh --build-remote` without being blocked by the
remote Docker Desktop keychain interaction path.

## Preconditions

- remote mini preview stack rebuilt from the current repo state
- Alembic migrated to `20260415_0026`
- one signed runtime site/key seeded on mini:
  - `site_id=site_smoke`
  - `key_id=key_default`

## Observed Results

1. `scripts/remote-preview-mini.sh --build-remote` completed successfully and
   ended with:
   - `preview ready: http://100.102.170.79:8010 (build mode: remote)`
2. mini `GET /health/operational-ready` returned `200`
3. mini observability summary showed all required workers fresh
4. projection cadence tasks became successful after migration and worker rerun
5. signed addon reads returned `source=projection` rather than
   `source=live_fallback`

## Signed Read Evidence

Observed response summaries:

- `/v1/addon/dashboard`
  - `source=projection`
  - `stale=false`
  - `fallback_reason=` empty
- `/v1/addon/providers/release-summary`
  - `source=projection`
  - `stale=false`
  - `fallback_reason=` empty

Representative values captured during the drill:

```json
{
  "path": "/v1/addon/dashboard",
  "source": "projection",
  "generated_at": "2026-04-15T01:52:10.444805Z",
  "fresh_until": "2026-04-15T01:54:10.444805Z",
  "stale": false,
  "fallback_reason": ""
}
```

```json
{
  "path": "/v1/addon/providers/release-summary",
  "source": "projection",
  "generated_at": "2026-04-15T01:52:10.365739Z",
  "fresh_until": "2026-04-15T01:57:10.365739Z",
  "stale": false,
  "fallback_reason": ""
}
```

## Issues Found During Drill

1. the mini database initially missed migration `20260415_0026`, causing
   `site_service_projections` lookup failures
2. the new worker entrypoints initially called `configure_logging()` without
   `settings.log_level`
3. the remote preview script could fail on Docker Desktop keychain access when
   trying to pull base images interactively

## Corrections Applied

- ran `alembic upgrade head` on mini
- fixed both worker entrypoints to call
  `configure_logging(settings.log_level)`
- changed `scripts/remote-preview-mini.sh` to:
  - use `--pull never`
  - include `proxy` in the managed preview stack
  - fall back to local image transfer when remote Docker keychain auth blocks

## Closure

This drill closes the projection-first acceptance gap for mini preview:

- Cloud owns addon read freshness semantics
- WordPress remains a light consumer
- remote preview rebuild is repeatable enough to serve as a real verification
  surface rather than a one-off manual rescue path
