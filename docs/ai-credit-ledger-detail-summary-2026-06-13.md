# AI Credit Ledger Detail Summary - 2026-06-13

Status: implemented in local commit `ffbb239`.

Purpose: summarize the AI credit ledger work that moved current-period
consumption from "estimate-first" presentation to ledger-backed detail views,
while keeping Cloud as a usage, entitlement, and billing detail surface.

## Background

The admin account page and Portal usage page needed to answer three questions:

- What is the current account's AI credit quota and used amount?
- Which consume records make up the current-period total?
- Which limits remain separate from AI credits, such as bound sites,
  concurrency, batch size, and vector capacity?

The product decision was to use a small, strict credit ledger instead of
showing only estimated consumption. AI credit consumption is now shown from
`credit_ledger_entries` when records exist. Meter-based estimates remain only
as a fallback when no ledger entries exist for the current period.

## Boundary Decision

This work stays inside the Cloud usage and entitlement detail boundary.

Allowed:

- account-level and Portal-visible usage detail
- current-period credit ledger read APIs
- AI credit quota and resource-limit display
- invariant tests for credit ledger writes

Not introduced:

- payment checkout
- wallet or balance top-up product surface
- invoice, dunning, or reconciliation front office
- a second WordPress control plane
- new infrastructure or orchestration

Local WordPress/plugin truth remains unchanged. Cloud only exposes hosted
runtime usage, entitlement, and billing detail.

## Implemented Backend Surface

Admin account credit ledger:

```http
GET /internal/service/admin/accounts/{account_id}/credit-ledger?limit=50&offset=0&source_type=
```

Portal account credit ledger through a site-scoped authorization path:

```http
GET /portal/v1/sites/{site_id}/credit-ledger?limit=25&offset=0
```

The response shape is intentionally list-oriented and paginated:

```json
{
  "account_id": "acct_example",
  "period_start_at": "2026-06-01T00:00:00+00:00",
  "period_end_at": "2026-07-01T00:00:00+00:00",
  "rate_version": "ai-credit-ledger-v2",
  "pagination": {
    "limit": 25,
    "offset": 0,
    "total": 1252,
    "has_more": true
  },
  "summary": {
    "total_credits": 1912,
    "entry_count": 1252,
    "breakdown": []
  },
  "items": []
}
```

Admin entries include internal identifiers such as account, subscription,
plan version, provider call, and metadata. Portal entries are sanitized to the
customer-facing usage fields needed for current-period consumption detail.

## Ledger Invariant

`consume.credit_delta` is now required to be an integer credit unit.

The repository rejects non-integer consume deltas before inserting a new ledger
entry:

```text
consume credit_delta must be an integer credit unit
```

This matches the product decision that the smallest visible AI credit unit is
`1`, not fractional values like `.285`.

Current rate version:

```text
ai-credit-ledger-v2
```

Current integer credit rules:

| Source | Rule |
|--------|------|
| Hosted runs | 1 credit per run |
| Model tokens | ceil(tokens / 1000) |
| Web search | 5 credits per call |
| Image recommendation | 3 credits per call |
| Other provider calls | 0 credits |
| Vector documents | 2 credits per document |
| Vector chunks | ceil(chunks / 10) |

## Frontend Surfaces

Admin account page:

```text
/admin/accounts/{accountId}
```

Adds a credit ledger detail section under the current usage and limits area.
It shows:

- current-period total ledger credits
- ledger record count
- recent consume entries
- source type
- quantity and unit
- consumed credits
- site/run context
- created time

Portal usage page:

```text
/portal/usage
```

Adds a user-visible current-period consumption detail section. The user sees
the same account-level period consumption through their authorized site context,
without internal metadata.

## Copy Change

Old page copy used "estimated credits" or "估算积分" as the default framing.
That is no longer accurate when ledger entries exist.

The new wording is:

- Ledger-backed values are described as recorded or ledger credits.
- Estimate/fallback wording appears only when no ledger entries exist.
- Separate resource limits are still named separately: bound sites,
  active API key sites, concurrent runs, batch items, vector articles,
  vector chunks, sync articles/run, and sync chunks/run.

The frontend was searched for stale wording:

```text
估算积分
估算積分
estimated credits
Estimated credits
credit ledger is enforced
统一积分估算
統一積分估算
```

No stale matches remained after the change.

## Verification

Final verification after commit `ffbb239`:

```bash
docker exec npcink-ai-cloud-api-1 python -m py_compile \
  app/adapters/repositories/commercial_repository.py \
  app/domain/commercial/mixins/_admin_mixin.py \
  app/api/routes/service.py \
  app/api/routes/portal.py

docker exec npcink-ai-cloud-api-1 ruff check \
  app/adapters/repositories/commercial_repository.py \
  app/domain/commercial/mixins/_admin_mixin.py \
  app/api/routes/service.py \
  app/api/routes/portal.py \
  tests/api/test_service_routes.py \
  tests/api/test_portal_routes.py

docker exec npcink-ai-cloud-api-1 pytest \
  tests/api/test_service_routes.py::test_admin_account_quota_summary_reports_ai_credits_and_resource_limits \
  tests/api/test_service_routes.py::test_admin_account_credit_ledger_lists_current_period_entries \
  tests/api/test_service_routes.py::test_credit_ledger_consume_credit_delta_must_be_integer \
  tests/api/test_portal_routes.py::test_portal_summary_usage_entitlements_and_audit_routes \
  -q

pnpm --dir frontend run type-check
pnpm --dir frontend run lint
pnpm --dir frontend run test:i18n:admin-portal-completeness
```

Results:

- backend compile passed
- ruff passed
- targeted pytest passed: 4 tests
- frontend type-check passed
- frontend lint passed
- admin/portal i18n completeness passed

Local service-layer check for `acct_site_npcink_local` returned:

```json
{
  "account_id": "acct_site_npcink_local",
  "total": 1252,
  "items": 3,
  "summary_total_credits": 1912.0,
  "rate_version": "ai-credit-ledger-v2"
}
```

## Browser Verification Note

Direct browser verification was not completed in that run because the in-app
Playwright profile was locked by another instance, and unauthenticated HTTP
requests to the admin and Portal pages returned login redirects.

The API, service-layer, type-check, lint, i18n, and route tests were completed.

## Files Changed In Commit

Backend:

- `app/adapters/repositories/commercial_repository.py`
- `app/domain/commercial/mixins/_admin_mixin.py`
- `app/api/routes/service.py`
- `app/api/routes/portal.py`

Frontend:

- `frontend/src/app/admin/accounts/[accountId]/page.tsx`
- `frontend/src/app/admin/page.tsx`
- `frontend/src/app/portal/usage/page.tsx`
- `frontend/src/lib/portal-client.ts`
- `frontend/src/lib/i18n.ts`

Tests:

- `tests/api/test_service_routes.py`
- `tests/api/test_portal_routes.py`

## Follow-Up Guidance

Keep future work aligned with this direction:

- Treat AI credits as integer ledger units.
- Keep site count, concurrency, batch size, and vector capacity as separate
  resource limits.
- Add pagination controls in the UI only when operators need deeper browsing
  beyond the latest ledger entries.
- Do not add commercial checkout, invoices, wallets, or self-serve payment
  flows until the product explicitly moves into serious commercial settlement.
