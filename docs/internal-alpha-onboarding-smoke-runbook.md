# Internal Alpha Onboarding Smoke Runbook

Status: active internal runbook
Date: 2026-06-11
Updated: 2026-07-16
Scope: platform administrator and customer user onboarding path before public release

## Purpose

This runbook proves the narrow internal alpha onboarding path:

`platform_admin -> account/package/subscription -> user access -> Portal login -> WordPress addon connection -> one-time server exchange -> signed runtime call -> usage and audit evidence`

It is not a GA checklist, a payment flow, a customer storefront, or a Cloud-side
WordPress control plane.

## Roles

- `platform_admin`: manages Cloud platform data, customer accounts, packages,
  subscriptions, diagnostics, audit, and trial readiness.
- `user`: logs in to Portal, authorizes an existing account-scoped WordPress
  addon connection, and views usage, billing, and audit. The user never manages
  signing keys directly.

## Fast Contract Smoke

Run from `/Users/muze/gitee/npcink-ai-cloud`:

```bash
pnpm run smoke:internal-alpha-onboarding
```

This is a fast API-level smoke. It creates an isolated temporary database and
verifies:

- platform admin account, Pro package coverage, and subscription setup;
- site administrator email-code login through `/portal/v1/auth/code/*`;
- WordPress addon connection through `POST /portal/v1/addon-connections`, after
  existing active account membership and `provision_sites` authorization;
- one-time server exchange through `POST /portal/v1/addon-connections/exchange`,
  with no key returned by the browser authorization step;
- one signed hosted runtime request through `/v1/runtime/execute`;
- usage meter evidence for runs and provider calls;
- Portal and Admin audit visibility for the onboarding actions;
- `trial_readiness.status == ready`.

## Full Local Alpha Smoke

After the fast contract smoke passes, run the existing local environment smoke:

```bash
pnpm run smoke:local-alpha
```

That path exercises the running Docker Compose stack, WordPress addon read path,
health readiness, provider/runtime execution, and evidence file generation under
`.tmp/local-alpha-smoke/`.

## Pass Criteria

- `pnpm run smoke:internal-alpha-onboarding` passes.
- `pnpm run smoke:local-alpha` passes for the chosen local or preview target.
- Admin account detail shows trial readiness as ready.
- Portal can load the selected site, connection/health evidence, usage,
  billing, and Cloud audit without exposing signing keys.
- WordPress remains the local binding and final-write owner.

## Boundary

Cloud remains the platform/admin, Portal, runtime, entitlement, usage, and audit
service layer. It does not own WordPress publishing, local approval, prompt
truth, router truth, workflow truth, MCP truth, or skill registry truth.
