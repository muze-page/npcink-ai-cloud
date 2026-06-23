# Admin Account Governance Lightweight - 2026-06-12

Status: active development decision.

Purpose: summarize the current platform-admin account management decision while
Npcink AI Cloud is still pre-release and internally tested. The goal is to keep
the operator surface usable without prematurely building a full enterprise
account-governance system.

## Current Roles

The platform currently has two practical identities:

- Platform admin: views and manages platform, customer, package, subscription,
  and support data.
- User: binds sites and manages their own site/workspace information.

The admin surface should stay customer-first. Platform admins need to answer:

- Which users/customers exist?
- Which package does each one currently have?
- Is the account active or suspended?
- What is the next small operator action?

## What Was Too Complex

The broader P2 proposal included:

- required suspension reasons
- full account operation timeline
- batch suspend/restore
- account archival or deletion
- owner/operator/support-readonly role splitting
- richer audit inspectors on the customer page

That is too heavy for the current stage. The project has not been publicly
released, there are no external production users, and the immediate pain is
operator clarity, not enterprise administration.

## Current Decision

Use lightweight account governance:

- Keep account `active` and `suspended` as the only exposed customer-account
  lifecycle states for now.
- Keep "Suspend account" and "Restore account" as explicit admin actions.
- Require confirmation before either action.
- Add a single optional suspension reason field in the suspend confirmation
  dialog.
- Store the latest suspension reason on account metadata as
  `account_status_note`.
- Store the latest status action timestamp on account metadata as
  `account_status_updated_at`.
- Show the suspension reason on the account list and account detail page when
  present.

This gives the operator enough context to avoid forgetting why an account was
suspended, without introducing a full audit-timeline product.

## Implementation Summary

Backend:

- `POST /internal/service/admin/accounts/{account_id}/suspend`
  accepts `{ "reason": "..." }`.
- `POST /internal/service/admin/accounts/{account_id}/restore`
  remains available and does not require a reason.
- `CommercialServiceAccountMixin.set_account_status()` writes the current status
  and lightweight metadata.
- Service audit events remain `account.suspend` and `account.restore`.

Frontend:

- The shared `ConfirmModal` can render optional form content.
- `/admin/accounts` shows "Suspend account" or "Restore account" per row.
- `/admin/accounts` suspend confirmation includes an optional one-line reason.
- `/admin/accounts/{accountId}` exposes the same action and reason input.
- Account list and detail surfaces display the latest suspension reason when it
  exists.

Tests:

- Service-route tests verify suspend reason persistence and account detail read
  back.
- Existing admin i18n, lint, type-check, and operator-path checks remain the
  regression baseline.

## Peer Practice Interpreted Conservatively

Comparable admin products usually separate reversible account blocking from
destructive deletion. That pattern is useful here, but only as a staging
principle:

- reversible suspend/restore is appropriate now
- destructive delete is not a default admin action now
- batch actions are not needed until operator volume proves they are needed
- role splitting is not needed until multiple real admin operators exist

The project should learn from those products without copying their whole
enterprise surface too early.

## Deferred

Do not implement these yet:

- batch account actions
- hard account delete
- account archive workflow
- full account audit timeline UI
- separate platform-admin roles
- multi-step incident or support playbooks

Revisit only when one of these becomes true:

- real operator volume makes one-by-one action too slow
- external users require support-history review
- multiple platform operators need permission separation
- deletion/retention policy becomes a release requirement

## Current Next Step

Use the lightweight suspend reason flow during internal testing. If operators
still cannot understand why an account is suspended, improve the copy or
placement of the latest reason before adding a larger governance system.
