# Admin Provider Management UI Simplification - 2026-06-30

## Status

Implemented in the Cloud admin frontend.

## Scope

This stage focused on the bounded admin surfaces for provider operations:

- `frontend/src/app/admin/ai-resources/page.tsx`
- `frontend/src/app/admin/ability-models/page.tsx`
- `frontend/src/lib/i18n.ts`
- `frontend/tests/unit/admin-ai-resources-contract.mjs`

The work stays inside the Cloud operator UI. It does not change provider runtime
APIs, routing truth, WordPress ability definitions, prompts, routers, approval
state, preflight, audit truth, or final WordPress writes.

## Product Direction

The provider management page should behave like a dense operations surface, not
like a dashboard landing page. The default view should answer:

- Which provider should I configure or test?
- What category and status is each provider in?
- Where do I add a provider?
- Where do I open low-frequency diagnostics?

Detailed runtime evidence, profile counts, write posture, and internal metadata
belong in diagnostics or technical detail surfaces, not in the default header.

## Decisions

### Header

The provider management header was simplified to:

- title and one short scope sentence on the left;
- one diagnostic action on the right.

The default header no longer shows:

- the `runtime resources` badge;
- connection, capability, profile, or write-posture metric chips;
- supplier add buttons.

Those values were useful for implementation verification, but they made the
default operator surface feel like a dashboard. Diagnostics remains the explicit
entry point for deeper runtime evidence.

### Supplier List Toolbar

The top supplier toolbar now owns only:

- model/capability supplier tabs;
- supplier search;
- the active add action.

`Add model supplier` and `Add capability supplier` are contextual actions in
the same toolbar position. Category and status filtering moved out of the
toolbar because those filters belong to table columns.

### Supplier Tables

The model and capability supplier cards no longer render inner titles or helper
copy before the table. The table starts immediately after the toolbar, reducing
vertical height and repeated explanations.

Capability supplier rows now expose category as a first-class column. Category
and status are filtered from their column headers:

- category: all, search, image, vector;
- status: all, ready, missing secret, disabled.

This makes the filter location match the data being filtered and removes the
previous visually loud category chips.

### Status Presentation

Normal ready/configured states were made quieter:

- ready badges use a muted class;
- normal enabled/configured state is compact text or hidden where redundant;
- missing credentials or disabled runtime calls still surface as row-level
  problems.

Recent test results show compact pass/fail summaries with timestamps. Successful
tests no longer render a large success badge in the default row.

### Capability Provider Configuration

Capability providers use a dedicated supplier-oriented form instead of exposing
model-provider controls by default. Internal bindings and low-frequency runtime
fields stay in technical/detail sections.

The built-in capability provider picker remains categorized in its modal because
that is a selection workflow, not the default list workflow.

### Search Provider Coverage

The search capability supplier set was expanded and checked around the active
operator needs:

- Apify;
- Tavily;
- Zhihu Search;
- Bocha;
- Jina Reader as reader enhancement rather than a primary search provider.

Search self-test output is localized for operators and stays attached to the
supplier row instead of sending users to a separate toolbox diagnostics page.

### Ability-Model Routing Surface

The ability-model routing page was tightened around plugin AI ability routing:

- plugin ability routes are grouped as route rows rather than repeated per-task
  fragments;
- audio routes are modeled as first-class route rows;
- route type, model configuration, runtime policy, and save action are visible
  in the same operating table;
- Cloud-native abilities remain a read-only runtime projection.

This keeps Cloud responsible for runtime model routing while preserving the
local WordPress path for ability definitions, prompts, approval, and writes.

## Non-Goals

This stage did not:

- create a second ability registry;
- create a second workflow registry;
- move prompt, router, preset, or MCP truth into Cloud;
- make Cloud a WordPress write owner;
- expose provider secrets to the browser;
- change runtime provider API contracts.

## Contract Tests

The admin AI resources contract test now guards these UI decisions:

- Provider Management remains a top-level admin entry.
- Ability-Model Routing remains a top-level admin entry, not an internal tab of
  Provider Management.
- Provider Management defaults to the supplier list workflow.
- Supplier add actions stay out of the primary header.
- The primary header does not render default runtime badges or metric chips.
- Supplier category and status filters live in table column headers.
- Supplier tables do not keep redundant inner list titles or helper copy.
- Capability supplier testing remains row-local and does not embed toolbox
  Cloud Checks.
- Normal ready/configured state remains visually quiet.
- Technical/internal runtime fields stay away from the default operator view.

## Verification

The focused verification gates used for this stage were:

```bash
pnpm --dir frontend run type-check
node tests/unit/admin-ai-resources-contract.mjs
git diff --check -- frontend/src/app/admin/ai-resources/page.tsx frontend/src/lib/i18n.ts frontend/tests/unit/admin-ai-resources-contract.mjs
```

For broader closeout, run the repo's normal frontend and quality gates before
release promotion.

## Follow-Up Suggestions

1. Smoke-test `/admin/ai-resources` at desktop and narrow widths to verify the
   table header filters remain usable.
2. Run the broader fast gate before merging:
   `pnpm run check:fast`.
3. Keep future provider detail additions behind diagnostics or technical
   disclosure sections unless they are needed for the default configure/test
   workflow.

## Closeout Addendum

The later cleanup in this stage settled the remaining provider ownership and
operator-flow questions raised during review.

### Supplier Ownership

The final provider split is:

- model suppliers own model platforms and model-serving endpoints, including
  text, image, audio, video, and embedding models;
- capability suppliers own non-model runtime sources, such as web search,
  stock-image sources, rerank providers, and vector stores;
- SiliconFlow is a model supplier, even when the selected model is an embedding
  model;
- TEI is treated as a self-hosted embedding model supplier, not as a default
  capability supplier;
- Site Knowledge can still bind to embedding models through the ability-model
  routing surface.

This keeps provider management aligned with the Cloud boundary: Cloud stores
runtime provider connections and model metadata, but does not create a second
ability registry or WordPress control plane.

### Default Capability Suppliers

The built-in capability supplier picker now focuses on the operator choices
that are actually capability sources:

- Search: Tavily, Bocha, Apify, Zhihu Search, and Jina Reader as URL reader
  enhancement.
- Image: Unsplash, Pixabay, and Pexels.
- Vector: Jina Rerank and Zilliz.

Embedding providers are intentionally absent from this picker. If a model
platform exposes embeddings, configure it as a model supplier and select the
embedding model from `/admin/ability-models`.

### Delete And Credential Channels

Provider connection rows now expose destructive delete only for DB-managed
connections. Built-in templates and read-only projections remain non-deletable.
The delete action uses the existing bounded provider-connection DELETE endpoint
with a confirmation step and idempotency key.

Multiple credentials for the same supplier are represented as additional
provider connection channels with priority and note fields. The UI labels this
as adding a credential channel instead of "backup" so it can cover primary,
secondary, quota-specific, or customer-account-specific keys without introducing
a separate credential orchestration surface.

### Env Migration

The provider `.env` migration path now maps embedding-capable platforms into
model supplier connections:

- `SILICONFLOW_*` imports to `siliconflow_env` with `text.ai` and
  `embed.default`.
- `OPENAI_*` imports to `openai_env` with `text.ai`, image generation, and
  `embed.default`.
- `TEI_*` imports to `tei_env` with `embed.default`.
- Jina rerank and Zilliz continue to import as capability suppliers because
  they are non-model capability sources.

The old `embedding_siliconflow`, `embedding_openai`, and `embedding_tei`
connection IDs are no longer generated by the importer or recommended in the
production runbook.

### Existing Data

Existing DB rows that were created under the earlier `embedding_provider`
classification are not deleted automatically. They may still be serving
existing Site Knowledge runs. Operators should delete those rows only after
confirming the runtime binding has moved to the intended model supplier.

### Ability-Model Routing And Audio Preview

The ability-model routing surface is the correct place to select embedding
models for self-developed abilities. Audio generation routes were also
collapsed into a single `wp-ai.audio-generation` profile, while summary-script
text stays on the short-text route. Audio preview can pass a preferred runtime
instance through policy so the dialog tests the selected model without changing
global routing truth.

### Verification Added

Additional tests now guard:

- capability suppliers do not default-expose embedding model providers;
- provider connection rows can be deleted only through the bounded DB-managed
  connection path;
- SiliconFlow imports as a model supplier, not as `embedding_siliconflow`;
- production runbook guidance no longer recommends old embedding-provider IDs;
- ability-model routing can bind Site Knowledge to embedding models without
  moving ability truth into Cloud.
