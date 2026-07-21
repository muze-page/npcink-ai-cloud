# P5-B3 WordPress Text Acceptance Closeout — 2026-07-18

Status: **P5-B3 engineering acceptance complete** on the exact revisions and
packages recorded below. Global P5, P5-B4 load/soak, and P5-B5 release closure
remain incomplete.

## Purpose

P5-B3 validates the WordPress-first hosted text loop for title suggestion,
summary suggestion, and selected whole-paragraph rewrite. The acceptance target
is an exact, reproducible local stack: Cloud executes a bounded hosted runtime
task, the WordPress editor exposes a reviewable suggestion, and one explicit
local save remains the only CMS write.

This record separates two inventories that serve different purposes:

1. the **central six-repository matrix** is Cloud plus the five local WordPress
   repositories;
2. the **Fresh six-plugin set** is the official WordPress AI plugin plus the five
   local plugins, and does not include Cloud.

## Boundary And Non-goals

- Cloud owns hosted execution, routing, provider/run metadata, usage evidence,
  health, and diagnostics only.
- WordPress remains the content and final-write truth. The editor performs local
  review and the accepted changes persist only after one explicit local save.
- Cloud output remains `suggestion_only=true` and
  `direct_wordpress_write=false`.
- The WordPress ability, editor, permission, review, and apply contracts do not
  move into Cloud.
- This batch does not claim a Core proposal, Core approval, Core preflight, or
  Core audit. Governance Core is installed as part of the exact stack but the
  accepted text path does not use it as audit evidence.
- This batch does not approve production deployment, production configuration,
  production credentials, a penetration test, or an external customer trial.
- This batch does not cover load/soak, current media replay, restore/release
  closure, additional CMS adapters, automatic apply, automatic publish, or
  compatibility aliases.
- The real-provider acceptance does not claim that a fallback route was used.
  Routing fallback remains Cloud profile policy; the Addon does not override it.

## Exact Revision And Package Inventories

### Central six-repository matrix

| Repository | Role in this batch | Exact revision | Version/package evidence |
| --- | --- | --- | --- |
| `npcink-ai-cloud` | hosted runtime and provider/run evidence | `fb3c1d7fcf678a45f79e476fe90343b38f313076` | application version `0.1.0`; source revision recorded, not a WordPress plugin ZIP |
| `npcink-abilities-toolkit` | local ability contracts | `77321e8b4f7502bb454b8ddbfbf14b46961619e9` | `0.5.3`; ZIP manifest below |
| `npcink-governance-core` | installed local governance component; no Core-audit claim in B3 | `af0e5128decb053bf0fa7a4e6448460e14d3f484` | `0.1.1`; ZIP manifest below |
| `npcink-ai-client-adapter` | local adapter component | `60b90fa71ce5270cc896624b1d8701cceec81a8d` | `0.3.2`; ZIP manifest below |
| `npcink-workflow-toolbox` | local product-surface component | `2c75273cb717eb3fc2214c42841ce84f269fa4b3` | `0.1.1`; ZIP manifest below |
| `npcink-cloud-addon` | signed Cloud transport and bounded error projection | `044c05f73201c5540977a90e518b3dc8295f3dbe` | `0.1.3`; ZIP manifest below |

The Cloud and Addon revisions are engineering branches for this acceptance.
Their presence here is exact-revision evidence, not an integration or
production-release assertion.

### Five local WordPress packages

| Component | Commit | Version | Exact package | SHA-256 | Integrity |
| --- | --- | ---: | --- | --- | --- |
| Abilities Toolkit | `77321e8b4f7502bb454b8ddbfbf14b46961619e9` | `0.5.3` | `npcink-abilities-toolkit-0.5.3.zip` | `652e6a1c7ae3d73dd40f53a47336287cc83155710eeb8bf323ccb77e78e4a0fb` | one root; ZIP test passed |
| Governance Core | `af0e5128decb053bf0fa7a4e6448460e14d3f484` | `0.1.1` | `npcink-governance-core.zip` | `ffb2f91bf4d9e9360699eb4c623d918da571915e3506b67a93b63f8daae25617` | one root; ZIP test passed |
| AI Client Adapter | `60b90fa71ce5270cc896624b1d8701cceec81a8d` | `0.3.2` | `npcink-ai-client-adapter.zip` | `cb949462169f3ed34076739a79b2470671b6128c6bb071d76ea709b0e612f00e` | one root; ZIP test passed |
| Workflow Toolbox | `2c75273cb717eb3fc2214c42841ce84f269fa4b3` | `0.1.1` | `npcink-workflow-toolbox.zip` | `fe43a597c3bcce5ca5816d0d038f3cc232704fde55a3f60dde34846aca67114b` | one root; ZIP test passed |
| Cloud Addon | `044c05f73201c5540977a90e518b3dc8295f3dbe` | `0.1.3` | `npcink-cloud-addon.zip` | `1097890377ac2cc8c88dcc0f890c0b0e9b0a59952b99147aa5aec037ebc468a1` | one root; ZIP test passed |

The package header versions matched the recorded versions. Build-only and test
scripts are not runtime package truth. A later package rebuild or source change
requires a new SHA-256 and a new exact replay.

### Official assets

| Asset | Version | SHA-256 | Verification |
| --- | ---: | --- | --- |
| WordPress Core official ZIP | `7.0.1` | `f171740cf45b1f5a1bf52194ca914787cd9d8ea078599b430eca951b62b2d000` | ZIP integrity and single `wordpress/` root passed |
| WordPress AI official plugin ZIP | `1.1.0` | `cec67bc85daa7b02a1444bc6ee808fcd151a6c7a249088ed6d16a4bee2335dcb` | ZIP integrity, single `ai/` root, and packaged version header passed |

## Fresh Environment

The final exact environment was rebuilt before the browser replay. It records
only non-secret runtime metadata:

- loopback origin `http://127.0.0.1:8898`;
- WordPress `7.0.1`;
- WordPress AI `1.1.0`;
- PHP `8.2.29` for the actual WordPress operations and MySQL `8.0.35`;
- `WP_ENVIRONMENT_TYPE=local` and plain permalinks;
- WordPress Core checksum passed;
- exactly the six plugins below were active, with no extra active plugin;
- the default sample plugins were removed;
- the environment was created stopped, with no Cloud identity, Addon/AI feature
  configuration, or listener until the acceptance controller took ownership;
- disposable site `site_p5b3_final_20260718` was provisioned against exact Cloud
  revision `fb3c1d7fcf678a45f79e476fe90343b38f313076`;
- account upsert, site provision, site activation, and key issuance each
  returned HTTP `200`; credential material was persisted with mode `0600` and
  was not emitted into evidence;
- the Addon was configured and verified through its actual Save-and-Verify
  path; the WordPress AI connector and the four required AI feature flags were
  enabled;
- unrelated monitoring, Site Knowledge delivery, and generation-reference
  features remained disabled;
- AI request logging was temporarily enabled only for the bounded metadata
  evidence and was disabled during cleanup.

### Fresh six-plugin set

| Plugin | Version | Source set | Verified state |
| --- | ---: | --- | --- |
| WordPress AI | `1.1.0` | official plugin asset | active |
| Abilities Toolkit | `0.5.3` | exact local ZIP | active |
| Governance Core | `0.1.1` | exact local ZIP | active |
| AI Client Adapter | `0.3.2` | exact local ZIP | active |
| Workflow Toolbox | `0.1.1` | exact local ZIP | active |
| Cloud Addon | `0.1.3` | exact local ZIP | active |

No MCP adapter, `wp-magick-toolbox`, default sample plugin, or unrelated
compatibility plugin belongs in this set.

## Acceptance Evidence

### 1. Data-path acceptance

The exact-revision data-path smoke passed on a deterministic temporary draft:

- title generation returned one suggestion without local acceptance;
- summarization returned one suggestion without local acceptance;
- selected whole-`core/paragraph` content resizing with `action=rephrase`
  returned one suggestion without local acceptance;
- suggestion generation left the stored title, body, draft status, and
  revisions unchanged;
- local acceptance applied the reviewed title, exactly one summary block, and
  only the selected whole paragraph while preserving the non-target sentinel
  and draft status;
- a second local apply was a no-op and created no revision;
- the temporary draft was deleted and cleanup was confirmed.

This smoke is data-path and idempotent-local-apply evidence only. It is not
browser-review or Core-audit evidence.

### 2. Final exact browser acceptance

The final browser replay ran from Cloud
`fb3c1d7fcf678a45f79e476fe90343b38f313076` and Addon
`044c05f73201c5540977a90e518b3dc8295f3dbe` against the loopback Fresh site.
It passed the complete user-facing editor loop:

- all three WordPress ability calls returned HTTP `200` through `POST`;
- content resizing used `action=rephrase`;
- the title suggestion was inserted into editor state;
- one generated summary was visible in editor state;
- selected whole-paragraph rewrite was reviewed through the localized
  Original/Suggested UI before Accept;
- the stored post and revisions remained unchanged before the explicit local
  save;
- pre-save WordPress post writes were `0`, explicit save writes were `1`, and
  revision delta was `+1`;
- the saved title, one summary group, and one rewritten target paragraph matched
  the reviewed editor state, while all non-target sentinels remain unchanged;
- exactly one paragraph carried the resize marker;
- the disposable draft and the single browser authentication session were
  deleted.

Screenshots contain only disposable fixture/review content. Machine-readable
evidence contains hashes and bounded metadata rather than generated content.

The decisive retained artifacts had these SHA-256 values at closeout:

| Artifact within `/tmp/p5b3-evidence-20260718` | SHA-256 |
| --- | --- |
| `browser-exact-final/wordpress-ai-text-review.png` | `c194c0448bc41c95d0a065c4f699e5bf6b81522bb56f9c90760e78ccbcd836ae` |
| `browser-exact-final/wordpress-ai-text-saved.png` | `8795eda84c80e4743eac02437f5f8137f5d7f59af7e09b59554e167fac1092d3` |
| `browser-exact-final-summary.json` | `a1271b9e800df3c7d79aee3bd5eddd78e798898f5306ea7b0b5195df07ffedb2` |
| `provider-run-evidence-exact-final.json` | `76b93f9c2fff90dc1dc1b629426afbf5d06a0dfc62e26d5b5528ff623d77d9c0` |
| `offline-summary.json` | `351f80002609fc9945ed1547b9bfbbc1948a1f0d4030350ef6bf256624adc9b0` |
| `final-exact-wordpress-finalize.json` | `b2a111b4e31088b86cd0cb7affd48b6956e4a6e7a1fd218c61a0428392caca11` |
| `final-exact-identity-cleanup.json` | `dd8af3d2c9b2d6b0aac0753a6437b9477ba85a54a53c59911048de79ceccd4a0` |

The bundle is local engineering evidence, not the P5-B5 release bundle. The
hashes make later substitution visible; they do not turn a temporary local
path into permanent release storage.

The final machine evidence records an identical SHA-256 for the summary and the
accepted rewrite. That does not invalidate the three distinct task calls, UI
review path, zero-write boundary, or one-save persistence proof, but it is a
real provider-quality limitation. P5-B3 is therefore contract/UI/write-loop
acceptance only: it is not provider editorial-quality approval, human copy
approval, or evidence that cross-task suggestions are sufficiently diverse.
That quality question requires a separate fixed-corpus evaluation rather than
being hidden by rerunning until a preferred output appears.

### 3. Deterministic transport-offline drill

The Fresh WordPress drill intercepted only the three Cloud runtime execution
requests and returned a deterministic transport failure. This is not a claim
that a real network outage or provider outage was exercised.

- three runtime requests were intercepted;
- title, summary, and rewrite all failed closed through bounded local error
  projection;
- the recorded local responses were HTTP `500` with bounded
  `prompt_builder_error` codes;
- WordPress fields and revisions remained unchanged;
- `direct_wordpress_write=false`;
- the disposable fixture was deleted.

### 4. Provider/run metadata

The signed read-only collector selected the latest complete trio after the
exact-replay cutoff. The three runs completed within a `32`-second evidence
window:

| Task | Run ID | Profile | Provider/model | Cloud duration | Provider calls | Result posture |
| --- | --- | --- | --- | ---: | ---: | --- |
| `title_generation` | `run_e15a1d2ee81a48cea9da20882343449c` | `wp-ai.short-text` | `openai` / `ByteDance-Seed/Seed-OSS-36B-Instruct` | `20,859 ms` | `1` | succeeded; suggestion only; no WordPress write |
| `content_summary` | `run_558ae4bb95be463ca286ed08e9fe2bae` | `wp-ai.editorial` | `openai` / `ByteDance-Seed/Seed-OSS-36B-Instruct` | `13,736 ms` | `1` | succeeded; suggestion only; no WordPress write |
| `content_rewrite` | `run_b37dae41909a479b8f4a1ae069edddff` | `wp-ai.editorial` | `openai` / `ByteDance-Seed/Seed-OSS-36B-Instruct` | `16,737 ms` | `1` | succeeded; suggestion only; no WordPress write |

The collector uses the signed read-only run path and an explicit metadata
whitelist. It records task, run ID, status, trace/profile/instance identifiers,
provider/model, call count, timing, and the no-write posture. Prompt text,
source content, generated result content, credentials, and raw Cloud envelopes
are omitted. Provider/run evidence does not create WordPress write authority.

## Real Retry And Repair Timeline

The acceptance was not declared from the first green narrow test. Failed
attempts were retained as diagnostic evidence, their disposable draft/session
state was cleaned, and each real failure produced a bounded regression fix:

1. **WP-CLI eval-file compatibility:** WordPress CLI prepends execution code,
   so a top-level strict-types declaration caused the Fresh PHP 8.2 smoke to
   fail before the product path ran. The smoke-only declaration was removed;
   product runtime strictness was not weakened.
2. **Fresh editor welcome overlay:** the initial browser attempt could not
   reach the title editor because the standard Fresh WordPress modal was
   visible. The browser smoke now dismisses visible startup overlays
   deterministically and asserts dismissal before AI review.
3. **CSS-transformed labels:** the next attempt reached all three ability calls,
   but visual CSS capitalization changed `innerText` for the localized
   Original/Suggested labels. The evidence check now compares DOM
   `textContent`, preserving exact localized semantics instead of testing
   presentation casing.
4. **Provider alternative bundle:** a real provider returned multiple rewrite
   alternatives plus an explanatory suffix. Cloud now extracts one bounded
   rewrite only when the complete response matches the exact alternative-bundle
   shape. Independent review rejected an overly broad first expression; the
   final expression is constrained to explicit meaning-preservation language,
   with negative tests proving legitimate multi-sentence text is not truncated.
5. **Chinese rewrite wrapper:** the final gate exposed a leading Chinese
   rewrite-label wrapper. Normalization now removes only an explicit,
   colon-delimited leading wrapper, while preserving the same phrase when it is
   ordinary body text. The full Cloud gate, not only the focused rewrite test,
   is required after this fix.
6. **Fresh acceptance-server execution ceiling:** the first exact `8898`
   browser attempt used the temporary PHP server's `30`-second execution limit.
   The request was terminated at about `31` seconds and WordPress surfaced its
   bounded critical-error `500` presentation. The CLI data-path trio still
   passed. The acceptance server was restarted with an explicit `120`-second
   limit and the complete browser loop then passed. This was an environment
   diagnosis and replay correction, not a product-code fix or a production
   timeout recommendation.

No step above is a compatibility layer for an obsolete public contract. These
are current-provider normalization and acceptance-harness corrections at the
current WordPress contract.

## Verification Gates

### Cloud

The final Cloud revision passed:

- `pnpm run check:fast`: contract suite `177 passed, 1 skipped`; domain suite
  `606 passed, 3 skipped`;
- focused WordPress rewrite API tests: `20 passed, 154 deselected`;
- focused domain wrapper and negative-preservation tests: `3 passed`;
- focused Ruff checks;
- `git diff --check`.

The full fast gate was rerun after the Chinese-wrapper fix; the closeout does
not rely on the focused rewrite tests alone.

### Cloud Addon

The final Addon revision passed:

- Node syntax check for the browser harness;
- PHP lint for the changed PHP harness/contracts;
- `composer test:all`, including static contracts and bounded failure
  projection;
- `git diff --check`;
- exact package ZIP integrity and one-root verification;
- the exact Fresh data-path, browser, and deterministic transport-offline
  smokes recorded above.

The final Addon ZIP SHA-256 is
`1097890377ac2cc8c88dcc0f890c0b0e9b0a59952b99147aa5aec037ebc468a1`.
Bounded error projection does not expose a raw Cloud payload or credential
material.

### Central six-repository matrix

The canonical `composer quality:matrix:run` command was run from
`npcink-workflow-toolbox`. All six configured repository gates passed: Cloud
plus Abilities Toolkit, Governance Core, AI Client Adapter, Workflow Toolbox,
and Cloud Addon.

The matrix snapshot was not a six-clean-repository claim. Cloud reported
`dirty=2` solely because two unrelated, user-owned M4 preview files were
untracked; they were preserved and were not staged, edited, or included in
P5-B3. The five WordPress repositories were clean at the matrix snapshot. A
strict clean-matrix replay remains part of P5-B5 release closure.

## Cleanup Receipt

Final exact-environment cleanup completed:

- temporary WordPress AI request logging was disabled;
- remaining P5-B3 fixture posts were `0`;
- the browser authentication session and final disposable draft had already
  been deleted by the passing browser harness;
- every key for `site_p5b3_final_20260718` was revoked, the site was suspended,
  and no credential value was emitted;
- the temporary PHP server was stopped and TCP `8898` had no listener;
- the disposable database was dropped and its `information_schema` count was
  verified as `0`;
- the Fresh filesystem root and task-owned provisioning, configuration,
  verification, evidence-collection, finalization, identity-cleanup scripts,
  and matching bytecode were removed;
- the redacted `/tmp/p5b3-evidence-20260718` bundle was intentionally retained.

The earlier disposable Fresh/preview identities were also closed: all three
previously issued keys were revoked across the two sites, both sites were
suspended, and the current-preview Addon connection and Addon-owned buffers
were cleared. No temporary credential-bearing path is recorded in this
closeout.

## Completion Decision

P5-B3 is complete for engineering acceptance on exactly the recorded Cloud
revision, Addon revision, official assets, and five local plugin ZIPs. The
evidence proves the current WordPress title, summary, and selected-paragraph
text loop, local review, Cloud zero-write posture, one explicit local save,
bounded offline failure, provider/run metadata, package integrity, and
disposable-environment cleanup.

Global P5 remains incomplete. P5-B4 load/soak and P5-B5 release closure remain
pending. P5-B5 still owns the strict clean-matrix replay, exact release bundle,
current media/text replay as required, restore rehearsal, release-policy proof,
and final requirement-to-evidence audit. B3 completion must not be read as
production approval, provider editorial-quality approval, media acceptance,
Core audit, or final refactor closure. Any change to a recorded revision,
package, runtime contract, provider normalization rule, or WordPress write
boundary requires new evidence rather than inheriting this result.
