# Python Type Checking Standard

Date: 2026-06-05

## Purpose

This document records the repository standard for Python type checking and
feature validation after the 2026-06 mypy cleanup.

The incident pattern was simple: feature-local checks passed, but full mypy had
historical repository debt. The fix was not to weaken mypy. The fix was to make
the validation lanes explicit.

## Core Rule

There are two different claims:

- Targeted validation means the changed feature surface is clean enough for the
  current task.
- Full validation means the entire `app` package is type-clean.

Do not substitute one claim for the other.

## Why Full Mypy Can Surprise You

`pyproject.toml` configures mypy with:

```toml
[tool.mypy]
packages = ["app"]
```

That makes the configured mypy scope the whole `app` package. A command that
looks file-scoped can still behave like a full package check when it uses this
configuration.

Because of that, feature-local pytest, ruff, or py_compile success does not
prove full-repository mypy success. It only proves the specific lane that was
run.

## Required Lanes

### Full Type Gate

Run this before merging broad backend changes and before claiming repository
type health:

```bash
.venv/bin/mypy app
```

Equivalent:

```bash
make mypy-full
```

This is the authoritative full-repository type gate.

### Targeted Type Gate

Run this for small feature work and changed-file validation:

```bash
bash scripts/mypy-targeted.sh
```

Pass explicit files when the changed surface differs from the default media
derivative files:

```bash
bash scripts/mypy-targeted.sh \
  app/domain/media_derivatives/contracts.py \
  app/domain/media_derivatives/processor.py \
  app/api/routes/media_derivatives.py
```

The targeted script uses an isolated temporary config without `packages =
["app"]` and runs with `--follow-imports=skip`. Its job is to check the
requested files without accidentally expanding the result into a full package
scan.

For commercial/runtime, entitlement, usage, Cloud Batch Runtime, or
Site Knowledge credit-ledger work, use the dedicated ratchet profile:

```bash
make mypy-commercial-runtime
```

This profile covers the commercial credit helpers, admin/runtime/billing mixins,
Site Knowledge credit metrics, runtime service, and entitlement route. It is the
minimum type gate before claiming that commercial/runtime type debt stayed
closed.

### Feature Runtime Gate

Run the tests that exercise the changed behavior. For media derivatives:

```bash
.venv/bin/pytest \
  tests/workers/test_media_derivative_worker.py \
  tests/api/test_media_derivatives.py
```

Targeted pytest proves behavior for the selected feature surface. It does not
prove full type health.

### Ruff Gate

For changed files, run the repository ruff command when feasible:

```bash
.venv/bin/ruff check <changed files>
```

If the exact ruff lane reports unrelated style debt, at minimum run:

```bash
.venv/bin/ruff check <changed files> --select I,F,E9
```

`I,F,E9` verifies import order, undefined names, and syntax-level failures. Do
not describe that as a full ruff pass.

## Development Workflow

1. Before editing, identify whether the task is feature-local or shared
   infrastructure.
2. For feature-local work, run targeted pytest plus targeted mypy on the changed
   surface.
3. For commercial/runtime, entitlement, usage, or Cloud Batch Runtime changes,
   run `make mypy-commercial-runtime` plus targeted pytest.
4. For shared service, repository, auth, worker, or mixin changes, also run full
   mypy.
5. Before claiming "mypy passes", run `.venv/bin/mypy app`.
6. If full mypy fails, classify whether the failure is caused by the current
   change or by documented existing debt. Since the 2026-06 cleanup, new full
   mypy failures should be treated as regressions unless proven otherwise.
7. Record any intentionally deferred debt in `docs/mypy-debt-baseline.md` or a
   follow-up document. Do not hide it in config.

## Prohibited Shortcuts

- Do not set global `ignore_errors = true`.
- Do not weaken `[tool.mypy]` to make a feature branch look clean.
- Do not claim full mypy health from targeted mypy output.
- Do not add broad `Any` or `cast` as a blanket escape hatch.
- Do not revert or reorganize unrelated dirty files while fixing type debt.

## Accepted Type-Fix Patterns

- Narrow external JSON and SQLAlchemy row payloads with `isinstance` checks or
  small coercion helpers before using `.get`, `int`, `float`, `dict`, or `list`.
- Use `Sequence[T]` instead of `list[T]` when a helper only reads items and must
  accept covariant lists from repositories.
- For mixin composition gaps, prefer explicit protocols or a typed shared base.
  A local `cast(Any, self)` is acceptable as a temporary bridge when runtime MRO
  already provides the method and the follow-up hardening path is documented.
- Keep external library typing narrow and local, especially for optional clients
  and integrations such as `pymilvus`.

## Reporting Standard

When reporting validation, list the exact lane and result:

- `targeted mypy`: command and file count/result.
- `full mypy`: command and full result.
- `pytest`: exact test paths and pass/skip count.
- `ruff`: whether it was full ruff or a narrowed `--select I,F,E9` check.

Use precise wording:

- Correct: "targeted mypy passed for the media derivative files."
- Correct: "full mypy passed: no issues in 139 source files."
- Incorrect: "mypy passed" when only targeted mypy was run.
- Incorrect: "ruff passed" when only `--select I,F,E9` was run.
