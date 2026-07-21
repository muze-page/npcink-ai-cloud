# Cloud Admin Phase D — Shared Diagnostic Shell Acceptance

Date: 2026-07-12
Surfaces: media observability, vector observability, and Agent feedback quality

## Change envelope

- Focused module: stable, presentation-only diagnostic primitives.
- Intended change: remove repeated alert and advanced-evidence shell markup after three accepted diagnostic pages proved the same behavior.
- Explicit non-goals: no shared data hook, query schema, anomaly model, business inspector, API client, mutation, or Cloud boundary change.
- Public contracts touched: two internal React components only.
- Rollback: inline the two presentation shells back into their three callers and remove the dedicated contract.

## Extracted primitives

- `BackofficeDiagnosticNotice`: consistent alert semantics, stale-snapshot copy slot, and initial-load retry action.
- `BackofficeDisclosure`: native `details`/`summary` shell with consistent spacing, border, dark theme, and customizable content layout.

## Deliberately local behavior

- URL parameter names and normalization.
- Request and telemetry normalization.
- Media failure, vector error, and feedback-quality queue semantics.
- Inspector fields, labels, thresholds, and boundary copy.
- Page-specific charts, tables, empty states, and filters.

## Acceptance

- A dedicated static contract confirms all three pages use the shared alert and disclosure primitives and no longer duplicate those shells.
- Targeted ESLint passed for the shared component, three pages, and three E2E specifications.
- Media, vector, and Agent feedback i18n contracts passed.
- Combined diagnostic E2E: 6 passed.
- Frontend type-check passed.
- `pnpm run check:fast`: 70 contract tests passed, 1 skipped; 192 domain tests passed, 3 skipped.
- The repository-wide frontend contract loop remains blocked by an unrelated, concurrently edited Portal billing validity-window contract.

## Next phase

Do not extract a universal queue yet. First review runtime diagnostics and plugin observability against the same shell, then decide whether their existing alert/disclosure markup is behaviorally identical. The next product-facing phase should address admin overview and navigation discoverability for the newly standardized diagnostic destinations.
