# Internal Alpha Onboarding Smoke Runbook

Status: active internal runbook
Date: 2026-06-11
Scope: platform administrator and site administrator onboarding path before public release

## Purpose

This runbook proves the narrow internal alpha onboarding path:

`platform_admin -> account/package/subscription -> site_admin_access -> Portal login -> site bind -> Cloud API key -> signed runtime call -> usage and audit evidence`

It is not a GA checklist, a payment flow, a customer storefront, or a Cloud-side
WordPress control plane.

## Roles

- `platform_admin`: manages Cloud platform data, customer accounts, packages,
  subscriptions, diagnostics, audit, and trial readiness.
- `site_admin`: logs in to Portal, binds their own site, manages site keys, and views
  usage, billing, and audit for their account/site scope.

## Fast Contract Smoke

Run from `/Users/muze/gitee/npcink-ai-cloud`:

```bash
pnpm run smoke:internal-alpha-onboarding
```

This is a fast API-level smoke. It creates an isolated temporary database and
verifies:

- platform admin account, Pro package coverage, and subscription setup;
- site administrator email-code login through `/portal/v1/auth/code/*`;
- site administrator-created Portal site through `POST /portal/v1/sites`;
- site administrator-issued Cloud API key through `POST /portal/v1/sites/{site_id}/api-keys`;
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
- Portal can load the selected site, key list, usage, billing, and audit.
- WordPress remains the local binding and final-write owner.

## Boundary

Cloud remains the platform/admin, Portal, runtime, entitlement, usage, and audit
service layer. It does not own WordPress publishing, local approval, prompt
truth, router truth, workflow truth, MCP truth, or skill registry truth.
