# Admin Ability-Model Routing UI History - 2026-07-01

Status: local implementation history.

Purpose: summarize the July 1 operator-review cycle for Provider Management,
Ability-Model Routing, Cloud runtime dependencies, and related admin/portal UI
cleanup. This document records why the UI was simplified and which historical
technical projections were removed from the default user-facing surfaces.

This document does not introduce a new API, product surface, routing contract,
ability registry, workflow registry, prompt editor, approval system, or
WordPress write path.

## Boundary

Npcink AI Cloud remains the hosted runtime and service-plane enhancement layer.

Cloud may own:

- hosted runtime execution;
- provider and model adapter configuration;
- runtime model binding for supported Cloud routes;
- usage, entitlement, health, diagnostics, and service-plane audit evidence;
- read-only metadata projections for operator diagnostics.

Cloud must not own:

- WordPress plugin ability definitions;
- plugin switches;
- prompts or presets;
- local approval and preflight;
- final WordPress writes;
- a second ability registry or workflow registry.

The July 1 cleanup kept `/admin/ability-models` as a runtime binding surface,
not a WordPress control plane.

## What Triggered The Cleanup

The review started from repeated operator confusion on
`/admin/ability-models`:

- Plugin AI tasks, audio routes, and Cloud runtime dependencies looked like
  separate product systems even though the operator sees them all as
  WordPress/plugin-initiated AI capabilities.
- Internal identifiers such as `wp-ai.short-text`, `profile`, provider adapter
  names, instance IDs, and raw runtime concepts were displayed as if they were
  operator decisions.
- Audio route configuration was split away from plugin ability-model routing,
  then duplicated as a separate default/profile preference flow.
- Provider/model selection did not make it clear that configured model
  suppliers should directly provide selectable runtime models.
- Normal states were visually over-emphasized while actual problems were not
  easy enough to scan.
- Table filters were placed above tables or in loud pill rows instead of next
  to the column being filtered.

The product conclusion was that the admin surface should expose the operator's
real task:

```text
choose which provider/model each WordPress plugin AI capability should use
```

It should not ask the operator to understand Cloud's internal profile topology
before they can route a capability.

## Product Decisions

### 1. Plugin AI capability routing is the main concept

The main page label is **Plugin AI ability routing** / **插件 AI 能力路由**.

The operator-facing row should read as:

```text
Ability scene -> type -> current model -> runtime policy -> configure
```

The row should not default-display internal config IDs, profile IDs, raw
instance IDs, or adapter implementation names. Those remain available only in
collapsed technical detail when useful for support.

### 2. Provider display uses the configured supplier name

Many upstreams use OpenAI-compatible APIs, but operators configure suppliers by
their Cloud provider connection name. Therefore the default model label should
use:

```text
Supplier display name / model id
```

Example:

```text
MQZJ / gpt-5.5
MiniMax / speech-2.8-turbo
DeepSeek / deepseek/deepseek-v4-flash
```

The adapter type, OpenAI-compatible transport, profile ID, and instance ID are
implementation details and should not be the primary label.

### 3. Audio routes belong inside plugin ability-model routing

Audio was previously exposed through a separate runtime profile preference.
That created the wrong mental model: operators saw the audio capabilities as
WordPress plugin AI capabilities, but the UI made them configure those
capabilities through a different mechanism.

The cleanup merged audio into the same routing table model:

- text capability routes select text models;
- image capability routes select image models;
- audio capability routes select audio models;
- audio preview is a helper inside the route configuration dialog.

`audio summary text` was removed as a separate plugin route because it is a
text summarization step and can reuse the short-text/editorial route class
instead of becoming an audio-specific route.

`article narration audio` and `audio summary playback` were also merged into
one audio-generation route because both choose a speech model for generated
audio playback. The distinction belongs to plugin prompt/context behavior, not
to a separate Cloud runtime model route.

### 4. Audio preview belongs in the route dialog, not as an independent workbench

The old audio workbench capability was useful for previewing voices, but as a
standalone admin entry it looked like a separate audio product surface.

The retained behavior is:

- audio preview lives in the route configuration dialog;
- the operator can customize preview text;
- preview uses the currently selected main model;
- preview does not save the route;
- preview does not write to WordPress;
- generated preview artifacts are proxied through an admin-safe preview route.

The standalone audio workbench entry should not be treated as a primary admin
destination.

### 5. Provider Management is the source of selectable models

The expected operator rule is simple:

```text
Add/configure a model supplier in Provider Management, then select its models in Ability-Model Routing.
```

DeepSeek, MiniMax, MQZJ, and similar providers should appear in routing
selection when their configured provider connection exposes compatible models.
Embedding-capable providers are model suppliers, not capability suppliers.

Capability suppliers are for non-model sources such as search, image sources,
rerank services, and vector stores. They should not be mixed with model
supplier routing priority.

### 6. Cloud runtime dependencies are read-only projections

The advanced Cloud runtime dependency area exists only to show Cloud-owned
runtime dependencies that are not ordinary plugin AI routes. It is not another
place to configure the same plugin abilities.

Rows such as Site Knowledge embedding can be configurable when Cloud supports a
bounded model binding. Rows such as Cloud-managed web search or image source
dependencies should clearly say they are managed by their supplier settings,
instead of showing a disabled or confusing configure button.

### 7. Normal status should be quiet

The default status column should not draw attention for healthy rows. Normal
rows use quiet text such as `Normal` or `Connected`. Problem states such as
missing provider, disabled supplier, unhealthy runtime, or unconfigured route
are the states that deserve emphasis.

### 8. Filters belong in table columns

Category and status filters were moved from top-level pill rows into the table
headers where possible:

- Provider Management uses category/status header filters.
- Cloud runtime dependencies use a category filter in the category column
  header.
- Supplier tables default to explicit `All categories` and `All statuses`
  options.

This keeps filtering close to the data being filtered and avoids creating a
second navigation layer above a simple table.

## Implemented Shape

### `/admin/ability-models`

The page now separates two bounded areas:

- plugin AI ability routing;
- advanced Cloud runtime dependencies.

Plugin AI ability routing:

- presents ability scenes as route rows;
- shows supplier/model labels rather than raw adapter names;
- keeps runtime policy concise;
- opens one configure dialog for model selection, fallback model, timeout,
  retry, and notes;
- supports provider and model search in the dialog;
- supports audio preview inside audio route dialogs;
- keeps technical IDs behind internal detail disclosures.

Cloud runtime dependencies:

- remain read-only by default;
- only expose bounded `Configure model` where Cloud supports it;
- explain managed dependencies through supplier settings;
- use a category select inside the category table header;
- only list category options that are present in the current rows.

### `/admin/ai-resources`

Provider Management now separates:

- model suppliers: model-serving providers for text, image, audio, video, and
  embedding models;
- capability suppliers: non-model runtime sources such as search, image
  source, rerank, and vector store providers.

Default tables are quieter and more task-oriented:

- category and status filters live in column headers;
- normal ready states are subdued;
- model supplier rows show compact enabled-model counts;
- model supplier priority is not shown because priority belongs to routing
  configuration, not provider identity;
- destructive delete uses inline confirmation instead of a browser-native
  confirmation dialog.

### Technical projection cleanup

Several admin and portal surfaces were cleaned up so technical support fields
do not become primary product labels:

- raw IDs, trace IDs, request IDs, subscription IDs, site IDs, and workflow
  metadata moved into support/technical detail sections where appropriate;
- `AI Advisor` was reframed as `Operations Advisor` / `运营诊断助手`;
- workflow metadata shows governance conclusions first and raw workflow fields
  behind technical detail;
- the legacy WordPress AI routing page redirects to the unified
  `/admin/ability-models` surface.

## Contract Tests Added Or Strengthened

The frontend contract tests now guard these decisions:

- Provider Management and Ability-Model Routing remain distinct top-level admin
  destinations.
- Legacy `/admin/wordpress-ai-routing` must redirect to
  `/admin/ability-models`.
- Cloud runtime dependencies must not duplicate plugin task rows.
- Internal profile IDs and instance IDs must stay behind collapsed internal
  details.
- Cloud runtime dependency category filtering must live in the category column
  header and must not expose empty hard-coded categories.
- Capability supplier category/status filters must live in table headers.
- Capability suppliers must not include model suppliers or embedding providers.
- Normal ready/configured states stay visually quiet.
- Technical support fields stay out of primary portal/admin labels.

## Verification Used During This Stage

Focused frontend gates used during the cleanup included:

```bash
node frontend/tests/unit/admin-ai-resources-contract.mjs
pnpm --dir frontend exec tsc --noEmit --pretty false
pnpm --dir frontend exec eslint src/app/admin/ability-models/page.tsx src/lib/i18n.ts tests/unit/admin-ai-resources-contract.mjs --max-warnings=0
pnpm --dir frontend run test:i18n-contract
```

Broader release or cross-repo closeout should still use the repository's normal
quality gates, especially:

```bash
pnpm run check:fast
```

## Follow-Up Rules

Future changes to these surfaces should follow these rules:

1. Prefer the operator's concept over internal Cloud topology.
2. Add model suppliers in Provider Management; select models in
   Ability-Model Routing.
3. Put route-specific model choices in Ability-Model Routing, not in provider
   rows.
4. Keep Cloud runtime dependencies as read-only projections unless a bounded
   Cloud-owned model binding exists.
5. Keep plugin switches, prompts, approvals, preflight, audit truth, and final
   WordPress writes outside Cloud.
6. Hide profile IDs, instance IDs, transport adapter names, trace IDs, and raw
   metadata behind support or technical detail disclosures.
7. Make normal states quiet and problem states scannable.
8. Put filters in the table columns they filter unless the workflow is a
   dedicated search/selection dialog.
