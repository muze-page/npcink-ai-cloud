# Credit Entitlement Closeout - 2026-07-06

Status: merged implementation summary.

This note records the package entitlement cleanup discussed and implemented on
2026-07-06. It is a historical handoff note, not a new control-plane contract.
The active code and contracts remain the source of truth.

## Context

The original user-facing package screen exposed too many quota cards:

- package points;
- site count;
- active API key sites;
- concurrent runs;
- batch items;
- vector documents;
- vector chunks;
- vector sync documents per run;
- vector sync chunks per run;
- tokens and runs in older admin summaries.

The admin package editor, however, only exposed a smaller structured package
field set such as included points, site limit, run count, token count,
concurrency, batch ceiling, and grace period. This made the product model look
inconsistent: customers saw more purchasable resources than operators actually
intended to manage.

The core product requirement was then clarified:

- AI credits are the only globally purchasable and consumable resource.
- A user's package quota is account-scoped. All bound sites share the same
  current-period quota for that account.
- Other operations should be priced or estimated into AI credits where they
  consume hosted AI value.
- Site count and Site Knowledge indexed article count may remain package
  capacity boundaries.
- Vector chunks, sync-per-run limits, runs, tokens, provider cost, batch size,
  and concurrency should not be customer-facing purchasable resources in this
  phase.

## Decision

Use a credit-first package model:

1. `ai_credits` is the only customer-visible consumable balance.
2. `bound_sites` is a package capacity limit, not a consumable credit balance.
3. `vector_documents` is a package capacity limit for indexed Site Knowledge
   articles. It is useful for tier differentiation.
4. `vector_chunks` and vector sync-per-run limits stay implementation detail
   unless a future contract explicitly promotes them.
5. `concurrent_runs`, `batch_items`, `runs`, `tokens`, and `provider cost`
   remain internal guardrails, diagnostics, or metering evidence. They are not
   separate purchasable package resources.
6. Runtime budget checks must respect the active entitlement snapshot for the
   current subscription period. The latest plan-version definition must not
   bypass the effective snapshot already assigned to a customer.

## Implemented Changes

PR: <https://github.com/muze-page/npcink-ai-cloud/pull/91>

Merge commit:

```text
78b4c257946d0f8dd8b2109d1123658c60d749d8
```

Important commits in the PR:

- `3a545a0c` - simplify package entitlement source.
- `30486630` - consolidate package consumption to AI credits.
- `a2fcd6ff` - fix billing plan-version typing exposed by CI mypy.
- `e1de2cf2` - use active entitlement snapshot budgets at runtime.

The implementation aligned these areas:

- Portal entitlement summary now exposes `ai_credits`, `bound_sites`, and
  `vector_documents` as the visible resource set.
- Portal no longer renders `concurrent_runs` or `batch_items` as customer quota
  cards.
- Admin/package detail continues to keep operator-side commercial detail, but
  customer-facing package consumption centers on AI credits.
- AI credit charge contracts state that AI credits are the only customer
  purchasable consumption budget.
- Runtime authorization estimates AI credit usage before provider execution and
  rejects over-budget requests before calling upstream providers.
- Runtime budget checks now use the active entitlement snapshot as the effective
  current-period limit, then add current-period top-up totals from subscription
  metadata.

## Local Baseline Reissue Used For Verification

During local verification, the current development database was reissued with a
clean published baseline:

| Plan | AI credits | Site limit | Vector documents | Batch items | Nightly runs |
|------|------------|------------|------------------|-------------|--------------|
| Free | 2,000 | 1 | 100 | 10 | 0 |
| Pro | 10,000 | 5 | 2,000 | 25 | 0 |
| Agency | 150,000 | 25 | 10,000 | 100 | 0 |

This was local verification evidence only. Target environments still need their
own explicit baseline reissue or migration before users can rely on these
values there.

## Verification Evidence

Local verification before merge included:

- `pnpm run check:fast`
- `.venv/bin/mypy app`
- `.venv/bin/python -m pytest tests/api tests/contract tests/domain -q`
  - result: `645 passed, 4 skipped`
- local API smoke:
  - `/api/health` returned healthy.
- local Portal entitlement smoke:
  - visible resource keys were `ai_credits`, `bound_sites`, and
    `vector_documents`.
  - `concurrent_runs` and `batch_items` were absent from the customer quota
    summary.

GitHub CI for PR #91 passed:

- PR body contract;
- backend;
- frontend;
- CodeQL;
- Secret scan.

## Boundary Notes

This change keeps Cloud inside its intended service-plane boundary:

- Cloud owns hosted runtime usage, commercial entitlement detail, billing
  evidence, ledger detail, and bounded Admin/Portal summaries.
- Cloud does not become a WordPress write owner.
- Cloud does not create a second ability, workflow, MCP, router, prompt, or
  preset control plane.
- WordPress/local plugin remains the control plane and final write truth.

The user-facing package model is account-scoped: one customer's current-period
credits are shared across all bound sites under that account. Site count only
limits how many sites the account may cover.

## Remaining Operational Work

Development code is complete for this phase. Production exposure still requires
separate release work:

1. Promote the merged `master` through the repository production release policy.
2. Reissue or migrate Free/Pro/Agency plan baselines in the target environment.
3. Smoke the target environment:
   - Admin plan detail shows the expected published plan version.
   - Portal entitlement summary shows only credits, bound sites, and vector
     documents.
   - Over-budget AI credit requests are rejected before provider execution.
4. Monitor credit ledger entries and customer-facing quota summaries after
   release.

Until that release work happens, this closeout should be treated as merged
development code, not as a completed production rollout.
