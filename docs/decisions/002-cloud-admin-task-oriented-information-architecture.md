# ADR-002: Use Task-Oriented Page Models For Cloud Admin

## Status

Accepted.

## Date

2026-07-12.

## Context

The Cloud admin surface contains 23 routes covering overview, customer service,
commercial records, providers, runtime diagnostics, service configuration, and
authentication. The routes evolved independently and converged on similar card
layouts even when their operator jobs differ.

This produced several recurring problems:

- working lists and actions appear below explanatory panels;
- success messages and audit receipts can compete with the primary task;
- detail pages expose too many mutations simultaneously;
- diagnostic routes repeat slightly different filters and state handling;
- route ownership is unclear when secondary routes are absent from navigation;
- large route files mix fetching, normalization, mutations, and presentation;
- mobile behavior often degrades to horizontal table scrolling.

The change must preserve Cloud's bounded service-plane ownership and must not
create a second WordPress control plane, registry, approval system, or write
authority.

## Decision

Adopt the task-oriented information architecture defined in
`docs/cloud-admin-information-architecture-v2.md`.

Every admin route declares one of six page models:

- `overview`;
- `queue`;
- `detail`;
- `configuration`;
- `diagnostic`;
- `authentication`.

Primary navigation is organized into Overview, Customer Operations, Runtime
Operations, and System. Secondary routes inherit a parent workspace. Route
paths remain stable during initial migration; presentation consolidation does
not merge APIs or data truth.

The migration uses three representative pilots before broad rollout:

1. customer detail;
2. service queue;
3. service settings.

Interaction structure is stabilized before large component extraction.

## Alternatives Considered

### Continue Page-By-Page Visual Cleanup

Pros:

- small diffs;
- immediate local improvements.

Cons:

- preserves inconsistent page jobs and navigation ownership;
- creates more page-local standards;
- cannot prove system-wide completion.

Rejected because visual convergence is not the same as operational coherence.

### Use One Universal Dashboard Template

Pros:

- strong visual consistency;
- easy shared component adoption.

Cons:

- lists, object details, configuration, diagnostics, and login have different
  jobs;
- encourages card mosaics and excessive summary content;
- weakens action and state hierarchy.

Rejected because consistency must exist at the contract level, not by forcing
all functions into one composition.

### Replace All Routes In One Large Rewrite

Pros:

- fast conceptual reset;
- fewer transitional states.

Cons:

- high regression and boundary risk;
- difficult to compare task and performance evidence;
- unsafe in an actively changing repository.

Rejected in favor of page-model pilots and phased migration.

## Consequences

- New or migrated admin routes must be classified in the route matrix.
- Page structure is selected from the operator job, not copied from a nearby
  route.
- Navigation labels and page titles must use the same domain vocabulary.
- Shared state, feedback, drawer, table, and receipt primitives may expand after
  pilot validation.
- Existing routes may temporarily retain legacy composition while migration is
  active; the contract test proves classification, not migration completion.
- Completion requires recorded functional, responsive, accessibility, safety,
  and performance evidence for the full route matrix.
- Cloud ownership and WordPress governance boundaries remain unchanged.
