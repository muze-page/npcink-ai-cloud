# Npcink AI Cloud Refactor Baseline — 2026-07-14

## Status

Pre-refactor local baseline; not a production benchmark.

This evidence records the repository snapshot before the P1-P5 refactor work
starts. It does not prove that any target contract is implemented, that a phase
has exited, or that a production SLO has been met.

## Environment And Limits

- Snapshot commit: `16cf860f`.
- Observation date: `2026-07-14`.
- Environment: local development Docker services with PostgreSQL, plus the
  repository-local `.venv` for focused pytest runs.
- There are no real users or production traffic in this evidence set.
- Durations below are local execution or mock-backed test times. They are not
  production provider latency, real WordPress latency, throughput, or SLOs.
- The dataset used by the PostgreSQL hot-path check was empty or small. Its
  query plans cannot be extrapolated to production cardinality or concurrency.

## Reproduction Commands

Run from the repository root at the recorded snapshot and retain the complete
stdout, stderr, environment description, dataset description, and commit:

```bash
pnpm run perf:runtime-hot-path:require-indexes

.venv/bin/pytest tests/api/test_wordpress_ai_connector_runtime.py -q --durations=10

.venv/bin/pytest \
  tests/contract/test_security_config_contract.py \
  tests/domain/test_callback_security.py \
  tests/api/test_runtime_payload_bounds.py \
  tests/api/test_media_derivatives.py \
  -q --durations=10

pnpm run check:fast
```

The structural counters are raw matching-line inventories over `app` and
`tests`, not occurrence or bug counts. Reproduce them with the searches below,
then classify each matching line against the deletion inventory:

```bash
rg -n 'wordpress_url' app tests | wc -l
rg -n 'wp_ai_connector_runtime\.v1|wp_ai_connector_result\.v1|validate_wordpress_ai_connector_runtime_contract' app tests | wc -l
rg -n 'blob_data' app tests | wc -l
rg -n '_source_bytes_b64|_watermark_bytes_b64' app tests | wc -l
rg -n 'public_download_token|playback_token|public-download' app tests | wc -l
wc -l app/domain/runtime/service.py app/api/routes/portal.py app/api/routes/service.py
```

## Current Results

| Gate | Result | Local timing / note |
| --- | --- | --- |
| `pnpm run perf:runtime-hot-path:require-indexes` | Passed; 6 queries; every expected index was available | Maximum reported PostgreSQL `Execution Time`: `0.527 ms` |
| WordPress AI connector runtime pytest | 45 passed, 1 warning | `11.79s`; slowest test `0.41s` |
| Security and media focused pytest | 50 passed, 1 warning | `9.31s`; slowest test `0.47s` |
| `pnpm run check:fast` contract suite | 80 passed, 1 skipped, 1 warning | `13.72s` |
| `pnpm run check:fast` domain suite | 233 passed, 3 skipped | `70.57s` |

The fast gate also emitted a frontend `pnpm.overrides` configuration warning.
The Python test output emitted a Starlette/httpx deprecation warning. Both are
retained here rather than being hidden by the passing status.

## Security Baseline

The focused security/media command covers the current automated tests for:

- security configuration;
- private-network callback rejection and baseline SSRF controls;
- runtime payload bounds;
- media site isolation, idempotency, expiry, and oversize rejection.

Its result was 50 passed, 1 warning in `9.31s`, with a slowest test of `0.47s`.
This is a local automated regression baseline. It is not a penetration test,
external attack simulation, or production security assessment.

## Performance Baseline

The PostgreSQL hot-path command passed its required-index availability gate for
all six queries. The reported `Execution Time` values, in command output order,
were:

| Query ID | Execution Time (ms) | Expected-index observation |
| --- | ---: | --- |
| `runtime_queue_claim_candidates` | 0.043 | Expected composite index available; not selected by this empty/small-data plan |
| `runtime_running_stale_diagnostics` | 0.010 | Expected composite index available; not selected by this empty/small-data plan |
| `runtime_callback_due_diagnostics` | 0.014 | Expected composite index available; not selected by this empty/small-data plan |
| `runtime_callback_dispatching_recovery` | 0.018 | Expected composite index available; not selected by this empty/small-data plan |
| `runtime_recent_nightly_runs` | 0.243 | No dedicated expected index is asserted by this command |
| `image_source_provider_metrics` | 0.527 | No dedicated expected index is asserted by this command |

The maximum was `0.527 ms`. These are local PostgreSQL execution times on an
empty or small dataset. Index availability is useful migration evidence, but
the planner's decision here is not evidence of the plan chosen at production
cardinality, and none of these values may be extrapolated to production.

The WordPress connector pytest result was 45 passed, 1 warning in `11.79s`,
with a slowest test of `0.41s`. That is mock/local test time, not provider
latency, queue latency, or a real WordPress end-to-end measurement.

## Structural Debt Counters

These marker values are raw matching-line counts in `app` plus `tests` at the
recorded snapshot. They are deletion-inventory counters, not occurrence counts
or counts of bugs, vulnerabilities, routes, or independent behaviors.

| Marker | Raw matching lines | Interpretation |
| --- | ---: | --- |
| `DEBT-P1-SITE-01` | `99` | Lines containing `wordpress_url` for P1 classification |
| `DEBT-P1-CONTRACT-01` | `17` | Lines containing one of the three superseded connector-contract markers for P1 classification |
| `DEBT-P3-BLOB-01` | `20` | Lines containing `blob_data` for P3 classification |
| `DEBT-P3-BASE64-01` | `4` | Lines containing `_source_bytes_b64` or `_watermark_bytes_b64`; excludes `b64_json` and provider-edge Base64 |
| `DEBT-P3-TOKEN-01` | `22` | Lines matching `public_download_token`, `playback_token`, or `public-download` for P3 classification |

Current module-size observations:

| File / symbol | Lines |
| --- | ---: |
| `app/domain/runtime/service.py` / `RuntimeService` | `8772` |
| `app/api/routes/portal.py` | `3864` |
| `app/api/routes/service.py` | `5214` |

Line counts are responsibility-extraction signals, not a mandate for a rewrite
or proof that every line is misplaced.

## Comparison Rules

- Compare a later run only when environment, database engine, dataset shape and
  size, command, and commit are recorded. Call out any difference instead of
  presenting unlike runs as a trend.
- Expected-index availability proves that the named index exists. It does not
  prove the production planner will select it at real cardinality or under
  concurrent load.
- Pytest duration measures local test execution. It must not be labeled as
  product, provider, queue, network, or real WordPress latency.
- Raw matching-line counts are interpreted only through the deletion-inventory
  rules. A lower number is not automatically better, and a nonzero number is
  not automatically a defect. The internal-media counter covers only
  `_source_bytes_b64` and `_watermark_bytes_b64`; it is not an inventory of all
  Base64 use.
- Provider-adapter transient Base64 required at the provider edge and historical
  migration definitions are allowed exceptions only after manual
  classification. They must not be silently counted as active public/runtime
  transport or persistence.
- Preserve warnings, skips, failures, and dataset limitations beside passing
  results.

## P1/P2/P3/P5 Re-measurement Plan

- **P1:** rerun the five raw searches and module line counts; run the focused
  target-contract tests and the required P1 check gates. Compare against this
  inventory only after manually classifying historical migrations and other
  allowed evidence.
- **P2:** use a real WordPress site to measure title, summary, and rewrite
  operations. Record end-to-end, queue, provider, and result-availability timing
  separately, together with run/provider evidence and confirmation that no
  Cloud-side WordPress write occurred.
- **P3:** measure several representative file sizes and record peak RSS,
  throughput, TTL, purge behavior, and cross-site denial. Add bounded-memory
  streaming evidence for upload, processing, and pull rather than relying on
  payload-size rejection tests alone.
- **P5:** run representative load and soak tests, a security assessment, and the
  exact deploy-bundle and central cross-repository matrix gates. Record dataset,
  concurrency, duration, commit, bundle identity, and complete failures or
  warnings.

## Known Gaps

- Existing media upload/download paths may still buffer whole objects, persist
  database blobs, or carry Base64. There is no bounded-memory streaming
  measurement yet.
- There is no production provider-latency evidence.
- There is no real WordPress end-to-end latency evidence for title, summary, or
  rewrite operations.
- There is no representative load or soak evidence.
- There is no penetration-test evidence.
- Empty/small local PostgreSQL plans do not establish production query-plan or
  capacity behavior.

These are open evidence gaps, not passing results.

## Exit Use

Use this record as the pre-change comparison point for P1, P2, P3, and P5. A
phase exits only with its own required contract, search, focused-test, real
smoke, security, performance, deployment, and matrix evidence. This baseline
does not waive any target-contract gate and is not proof that the refactor is
complete.
