# Release Readiness History - 2026-07-06

Status: local closeout summary before production promotion.

This document records the pre-release cleanup pass completed on 2026-07-06,
while Npcink AI Cloud still had no real public users. It summarizes the
historical burden removed, the Cloud boundary that stayed intact, the
verification gates that passed, and the operator work that remains outside this
code commit.

## Context

The cleanup started from a request to inspect historical implementation
burden before first release and remove avoidable compatibility debt while the
project still had no real user migration burden.

The main problems were:

- Portal emails still used engineering-style copy, plain test language, and
  weak sender presentation.
- Admin service settings exposed rarely changed SMTP configuration too
  prominently and lacked a safe email preview surface.
- Visible Cloud identity and active defaults still contained older Magick-era
  or placeholder naming in several active paths.
- Admin and Portal session cookies still used `magick_*` names as the active
  runtime cookie names.
- Local and remote smoke scripts still used or expected older env var names,
  old response fields, old WordPress addon strings, or a fixed provider default.
- Anti-drift needed a concrete task contract describing this release-readiness
  cleanup.

The cleanup goal was to turn this historical residue into a current, releaseable
Npcink baseline before production validation.

## Boundary Held

This cleanup stayed inside the existing Cloud responsibility boundary:

- Cloud remains the hosted runtime, service evidence, Admin detail, Portal
  detail, usage, entitlement, health, and diagnostics layer.
- WordPress/local plugin remains the control plane and final write truth.
- Cloud did not add a second ability registry, workflow registry, MCP platform,
  OpenClaw control plane, prompt/router/preset truth, approval system, or
  WordPress write owner.
- No new infrastructure was introduced. The implementation stayed within the
  existing FastAPI, PostgreSQL, Redis, worker, Docker Compose, and frontend
  stack.

## Implemented Changes

### Portal email experience

- Added a registration-specific email sending path instead of reusing the login
  template.
- Reworked SMTP email subjects, plain-text bodies, and HTML bodies for:
  - test email;
  - login verification code;
  - registration verification code;
  - email change verification;
  - email changed notice.
- Normalized project display names so user-facing subjects do not expose
  underscore-style internal names.
- Added backend tests for human-readable email templates and HTML/plain text
  multipart output.

### Admin service settings UI

- Folded rarely changed SMTP configuration behind a summary/edit interaction.
- Added sender-name recommendation copy centered on `Npcink AI Cloud`.
- Added an admin email preview path that renders real backend email templates
  without sending email or saving configuration.
- Moved the preview into a focused drawer-style surface so the main settings
  page stays operational rather than documentation-heavy.
- Added frontend UI contract coverage for the folded SMTP and preview behavior.

### Active naming and default cleanup

- Updated active UI copy and defaults from older Magick-era branding to Npcink
  branding where they were still part of runtime, Admin, Portal, or deployment
  defaults.
- Updated AI-generated content disclosure text to use Npcink identity.
- Updated frontend Docker defaults to the current production domain.
- Updated README's active admin cookie description to the current cookie name.
- Cleaned active scans so old placeholder domains and old sender names no
  longer remain outside historical legacy-contract material.

### Cookie and env cleanup

- Switched active Admin and Portal cookies to `npcink_*` names.
- Kept old `magick_*` cookie names only as legacy deletion targets so browsers
  are cleaned up during migration.
- Updated frontend proxy/bootstrap handling and backend auth/session routes to
  issue current cookies and expire the legacy cookies.
- Updated release smoke, secret rotation, local alpha drill, and remote runtime
  script env names from older Magick-era names to current `NPCINK_CLOUD_*`
  names.

### Smoke and anti-drift repair

- Added `task-contract-release-readiness-cleanup-2026-07-06.json` so
  anti-drift can classify this cleanup as an explicit Cloud detail change.
- Refreshed `scripts/local-alpha-smoke.sh` to match current contracts:
  - WordPress addon page detection now checks the stable addon admin shell
    instead of old English `Cloud API Key` copy.
  - Portal login verification now checks `data.principal_id`.
  - Admin session verification now checks `data.principal_id`.
  - Provider checking is no longer hard-coded to `openai`; operators can still
    opt in with `NPCINK_CLOUD_EXPECTED_PROVIDER_ID`.

## Verification Evidence

The following checks passed locally during closeout:

- `git diff --check`
- residual scan for committed secrets and active old naming/default residue
- `pnpm run check:release-policy`
- `pnpm run check:frontend-locks`
- `pnpm run check:anti-drift`
- `pnpm run check:perimeter`
- `pnpm run check:fast`
- `pnpm run frontend:type-check`
- `pnpm run frontend:test:i18n-contract`
- `node frontend/tests/unit/admin-service-settings-ui-contract.mjs`
- targeted frontend ESLint for edited service-settings and i18n files
- targeted backend pytest for email preview and admin cookie behavior
- `NPCINK_CLOUD_SECRET=npcink-cloud-test-secret pnpm run smoke:local-alpha`

The latest local alpha smoke evidence file from this pass was:

```text
.tmp/local-alpha-smoke/evidence-20260706093131.json
```

The smoke confirms:

- local Cloud dev services start;
- local WordPress is reachable;
- WordPress Cloud addon admin page is found and verified;
- Portal membership and billing bootstrap work;
- Admin and Portal sessions load through current session contracts;
- runtime execution succeeds;
- OpenClaw read-only analysis remains report-only and does not require local
  approval;
- usage and usage-meter checks complete.

## Operator Notes

The operator confirmed that the production sender name and sender mailbox were
already updated online. This commit therefore keeps code defaults and guidance
clean, but does not attempt to edit production `.env.deploy` or server-side
application code.

No stage, push, or deployment was performed as part of the closeout before this
documentation record. Production promotion should still follow
`docs/cloud-production-release-policy-v1.md`.

Before production validation, confirm:

1. the intended branch and commit are deployed from Git, not edited directly on
   the server;
2. production `.env.deploy` has current domain, trusted origin, SMTP sender,
   session secrets, internal token, and provider keys;
3. database and `.env.deploy` rollback paths are known;
4. release scope is intentional and rollback is known;
5. the production release policy approval phrase is present when promoting to
   `production`;
6. remote smoke is run against the target host after deployment.

## Practical Rule Going Forward

While the project still has no real users, remove stale active naming and
contract residue directly when it is not part of an explicit compatibility
contract. Preserve old names only in historical documents, migration notes, or
legacy cleanup code that actively expires old client state.

If a future cleanup touches abilities, workflows, MCP, OpenClaw, prompts,
router/preset truth, approval, or WordPress writes, stop and route the change
through the relevant boundary document before implementation.
