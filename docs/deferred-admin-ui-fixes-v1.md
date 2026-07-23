# Deferred Admin UI Fixes v1

Status: active backlog

Created: 2026-07-23

Scope: small, reproducible Cloud Admin UI defects intentionally deferred for a
focused repair batch.

This document is a temporary repository-local source of truth while the GitHub
issue connector is unavailable. Each item should be converted to a GitHub issue
before implementation, then closed here with the issue or pull-request link.
It is not an authorization to broaden the Admin surface or change runtime
contracts.

## ADMIN-PROVIDER-001: hidden connection ID can freeze at one character

Status: deferred

Priority: P2; configuration-blocking when triggered, with a bounded workaround

Surface: `/admin/ai-resources`, new model-provider connection dialog

Observed: 2026-07-23 on the first production-validation installation

### Symptom

Creating an OpenAI-compatible connection with display name `MQZJ` can fail with:

```text
connection_id must be 2-64 lowercase characters using letters, numbers, dot, dash, or underscore
```

The visible display name, base URL, and credential may all be valid. The failed
field is the internally generated `connection_id`, which is not visible for the
selected preset.

### Reproduction

1. Open the new provider-connection dialog.
2. Use the OpenAI-compatible preset.
3. Enter a replacement display name progressively, character by character.
4. Enter a valid base URL and credential.
5. Fetch the model catalog or save the connection.
6. Observe that the backend may receive a one-character connection ID and
   reject the request.

Do not retain real credentials, request bodies, or screenshots containing
secrets as reproduction evidence.

### Root cause

The display-name change handler in
[`frontend/src/app/admin/ai-resources/page.tsx`](../frontend/src/app/admin/ai-resources/page.tsx)
derives a connection ID only while the current value is falsey. The first
character can therefore produce a truthy one-character slug such as `m`, after
which later display-name changes no longer update it.

The backend validator in
[`app/domain/provider_connections/service.py`](../app/domain/provider_connections/service.py)
correctly lowercases identifiers and requires the pattern
`^[a-z0-9][a-z0-9_.-]{1,63}$`. Backend validation should not be weakened to
accommodate the hidden frontend state.

### Current workaround

- Close and reopen the dialog, then paste the complete display name in one
  operation; or
- keep the preset's default display name for the first save and rename the
  display label afterward.

Examples of valid final IDs include `mqzj` and `mqzj_primary`. A one-character
ID, URL, whitespace, slash, colon, or Chinese character is not valid.

### Required fix

Keep explicit UI ownership state for the generated identifier:

- while the operator has not edited the connection ID, continuously regenerate
  it from the complete display name;
- after an explicit connection-ID edit, preserve the operator value;
- do not let intermediate typing create a hidden invalid final value;
- validate before the network request and show a localized, field-level error;
- keep frontend normalization aligned with the backend contract.

### Acceptance criteria

- Character-by-character entry of `MQZJ` submits `mqzj`.
- Pasting `MQZJ` submits `mqzj`.
- Preset defaults continue to produce a valid stable identifier.
- Custom-provider connection IDs remain editable and are not overwritten after
  explicit user input.
- Invalid identifiers are blocked locally with an actionable localized error;
  the raw backend message is not the only feedback.
- Unit or contract coverage reproduces progressive input and the transition
  from generated to explicitly owned identifier state.
- No credential value is logged, returned, or added to test fixtures.

### Non-goals

- Do not loosen the backend identifier pattern.
- Do not change provider credentials, catalog APIs, runtime routing, abilities,
  prompts, workflows, or WordPress write ownership.
- Do not expose low-frequency internal fields on the default Admin surface
  unless field-level recovery cannot otherwise remain understandable.

### Closure record

- GitHub issue: pending
- Pull request: pending
- Verification: pending
