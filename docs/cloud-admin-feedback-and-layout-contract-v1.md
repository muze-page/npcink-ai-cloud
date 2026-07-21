# Cloud Admin Feedback And Layout Contract v1

Status: active.

Purpose: keep the platform-admin workspace task-first, stable during mutations,
and auditable without turning operation receipts into primary page content.

## 1. Scope

This contract applies to `frontend/src/app/admin/**` and shared admin UI
components. It governs page hierarchy, mutation feedback, form errors,
background work, and audit receipt presentation.

It does not change Cloud API contracts, authorization, audit persistence,
provider routing, local plugin truth, WordPress approval, or WordPress writes.

## 2. Product Boundary

The admin workspace is a bounded `platform_admin` service-plane surface. It may
operate Cloud-owned accounts, sites, commercial records, provider connections,
runtime diagnostics, service configuration, and audit evidence.

It must not become a second WordPress control plane, local ability registry,
workflow registry, prompt/router/preset owner, or WordPress write owner.

## 3. Page Hierarchy

Admin pages should follow this order when the content exists:

1. compact page title and primary cross-page actions;
2. optional compact summary metrics;
3. task toolbar with tabs, search, filters, and create actions;
4. primary table, list, or focused working surface;
5. contextual drawer or dialog for create, edit, inspect, and audit detail.

The page title or summary panel must not become a catch-all container for
mutation notices, receipts, forms, diagnostics, and secondary help.

Persistent boundary guidance should use a concise information hint or nearby
help entry. It should not interrupt the primary task on every visit.

## 4. Feedback Taxonomy

### 4.1 Transient success

Use the global Toast surface for completed save, test, enable, disable, delete,
copy, and refresh operations when no further operator decision is required.

- Toast must not change document flow or move the table.
- Default duration is 5 seconds.
- Copy names the affected object and the completed outcome.
- A success Toast may point to persistent audit detail.

### 4.2 Contextual form feedback

Keep validation, credential, and test failures inside the active dialog,
drawer, or field group when the operator must correct the current form.

- Field errors stay below the affected field.
- Form-level errors stay near the form actions.
- Corrective feedback remains until resolved or dismissed.

### 4.3 Page-blocking failure

Use a persistent inline alert at the affected data surface when the page cannot
load or the primary task cannot continue. Include a retry action when retry is
safe and meaningful.

### 4.4 Background operation

Show queued or running work on the affected row or in a bounded task-status
surface. Do not represent unfinished work as a success Toast.

### 4.5 Auditable mutation receipt

Every governed Cloud mutation that returns an audit receipt must preserve it.
The receipt is durable follow-up evidence, not a second success banner.

- Keep the latest receipt reachable from the task toolbar, affected object, or
  contextual detail surface.
- Open full receipt data in a dialog, drawer, or dedicated audit view.
- Preserve copyable receipt text, audit filters, scope, outcome, and audit event
  reference.
- Do not permanently expand the page title or summary panel with receipt cards.

## 5. Interaction Rules

- Create and edit flows use a dialog or drawer when the list remains the main
  task.
- Successful mutations refresh the affected row without resetting unrelated
  filters or scroll position.
- Destructive actions require confirmation and identify the affected object.
- Loading, empty, error, success, and disabled states must remain distinct.
- Feedback must be announced with the appropriate `status` or `alert` live
  region without announcing normal page content as an error.
- Keyboard focus must remain in the active dialog and return to a meaningful
  trigger after close when the shared dialog primitive supports it.

## 6. Visual Rules

- Use one primary accent and the existing admin neutral palette.
- Avoid nested full-width cards when spacing or a single divider communicates
  the hierarchy.
- Keep tables and toolbars stable when transient feedback appears.
- Prefer compact status text or badges on the affected row over detached status
  panels.
- Dark mode and light mode must preserve the same information hierarchy.

## 7. Supplier Page Pilot

The supplier workspace is the first implementation of this contract:

- save, delete, and standalone connection-test outcomes use global Toast;
- form-specific guidance and failures stay in the provider dialog;
- the latest backend receipt remains stored;
- a compact `Latest operation` toolbar action opens receipt detail;
- the page summary no longer renders duplicate success and receipt cards.

## 8. Verification Gates

For a feedback or layout change, run the narrowest applicable set:

```bash
pnpm --dir frontend run type-check
pnpm --dir frontend run lint
pnpm --dir frontend run test:i18n-contract
pnpm --dir frontend run test:contracts
pnpm run check:fast
```

Also inspect the changed route at desktop and narrow mobile widths in both
light and dark mode when the change affects shared visual primitives.
