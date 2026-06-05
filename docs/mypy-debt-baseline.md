# Mypy Debt Baseline

Date: 2026-06-04

Daily development rules now live in
[`docs/python-type-checking-standard.md`](python-type-checking-standard.md).

## Current State

The full mypy lane is the repository-wide type gate:

```bash
.venv/bin/mypy app
```

Initial reproduction on 2026-06-04 failed with 780 errors across 46 files, while
checking 138 source files. After the cleanup pass on the same day, the full lane
passes:

```text
Success: no issues found in 139 source files
```

The repository `pyproject.toml` includes:

```toml
[tool.mypy]
packages = ["app"]
```

That makes the configured mypy scope represent the full `app` package. Keep the
full lane as the authoritative repository gate, and keep the targeted lane for
narrow change validation so small feature work can be checked quickly without
accidentally expanding command-line file arguments back into a full package run.

## Debt Cleared In This Pass

- `callback_security`: callback signing inputs and optional payload boundaries.
- SQLAlchemy repositories: statement filters, scalar results, row payloads, and
  optional values.
- Runtime service: payload narrowing, optional timestamps, provider/run
  boundaries, and error typing.
- Commercial mixins: structural typing drift between mixins and the composed
  service, especially billing/admin/account/site/runtime helper methods and
  cross-mixin serializers.
- Usage rollup/service: SQLAlchemy aggregate row typing and broad payload
  values flowing into `int`, `float`, lists, and dicts.
- Observability plugin/site overview: external metric payloads and event payloads
  need local narrowing before primitive conversion.
- Worker summaries: router diagnostics, performance snapshot, latency probe,
  provider degradation, heartbeat, ops cadence, runtime queue, and callback
  dispatch payload coercion.
- `site_knowledge` / `pymilvus`: local narrowing around external payloads and
  optional vector client fields.
- Auth/PyJWT: decoded payload narrowing before subject and token field access.
- Media derivatives: targeted feature files now pass both targeted and full
  mypy checks.

## Layered Strategy

- Full baseline: run `make mypy-full` or `.venv/bin/mypy app` to see the complete
  repository debt state.
- Targeted check: run `make mypy-targeted` for the media derivative default
  files, or pass files explicitly:

```bash
bash scripts/mypy-targeted.sh \
  app/domain/media_derivatives/contracts.py \
  app/domain/media_derivatives/processor.py \
  app/api/routes/media_derivatives.py
```

The targeted script uses an isolated temporary mypy config with no `packages`
entry and `--follow-imports=skip`, so it checks the requested files without
pulling the full `app` package into the result. `app/domain/runtime/service.py`
has been cleaned up and can participate in full-repository validation, but keep
targeted defaults focused on the changed feature surface.

## Follow-Up Hardening Order

1. Replace commercial mixin `cast(Any, self)` bridge calls with explicit mixin
   dependency protocols or a shared typed base.
2. Move repeated payload coercion patterns into small shared helpers where that
   reduces duplication without hiding validation behavior.
3. Add regression tests around runtime service and commercial billing/admin
   flows that were historically type-fragile.
4. Keep `site_knowledge` / `pymilvus` external typing narrow and local as those
   integrations change.
5. Treat full mypy as required in CI, and use the targeted lane as the fast
   developer check for changed files.

Do not use a global `ignore_errors = true` or equivalent broad suppression to
hide new problems. Prefer targeted checks plus narrow, documented fixes for each
debt cluster.
