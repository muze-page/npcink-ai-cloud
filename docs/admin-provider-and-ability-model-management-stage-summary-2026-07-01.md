# Admin Provider And Ability Model Management Stage Summary - 2026-07-01

## Status

Implemented as local Cloud admin frontend iteration history.

This document summarizes the operator-review cycle around Provider Management,
Ability-Model Routing, model reference metadata, and related admin UI cleanup.
It records the product boundary and the current operating model so later work
does not reintroduce the same complexity.

## Boundary

Npcink AI Cloud remains the hosted runtime enhancement layer.

Cloud may own:

- runtime provider connections and masked credential storage;
- provider-visible model catalogs;
- lightweight model reference metadata for operator inspection;
- runtime model binding for Cloud-supported ability routes;
- read-only usage, health, telemetry, and diagnostic evidence.

Cloud must not become:

- a second WordPress control plane;
- a second ability registry;
- a second workflow registry;
- prompt, router, preset, MCP, or OpenClaw truth;
- final approval, preflight, audit, or WordPress write owner.

Provider Management and Ability-Model Routing are therefore admin operating
surfaces, not product-authoring surfaces.

## Problems Found During The Review

The initial Cloud AI provider setup was hard to operate because:

- provider credentials were split across environment variables and UI state;
- operators could not tell which feature used which provider/model;
- model suppliers and capability suppliers were mixed together;
- old web-search and image-source pages created multiple configuration entry
  points;
- model visibility, model intelligence, and ability routing were scattered;
- technical details such as profile ids, workflow metadata, and raw provider
  scopes were shown too prominently;
- normal statuses and repeated explanatory copy made the tables noisy;
- destructive provider deletion was too easy to click.

The main product goal became:

```text
Configure provider connections once, expose their available models, and choose
which model each runtime ability should use from a separate routing surface.
```

## Final Operating Model

### Provider Management

`/admin/ai-resources` is the consolidated supplier management entry.

It contains two supplier categories:

- model suppliers: OpenAI-compatible, New API / One API, DeepSeek, MiniMax,
  SiliconFlow, OpenRouter, Anthropic, and custom model endpoints;
- capability suppliers: search, image-source, rerank, and vector-store
  providers such as Tavily, Bocha, Apify, Unsplash, Pexels, Jina Rerank, and
  Zilliz.

The retired `/admin/web-search` and `/admin/image-sources` concepts are moved
into Provider Management as capability suppliers.

Model suppliers do not show provider priority. A model supplier provides models;
priority only matters where a runtime ability chooses which model or fallback
model to call.

Capability suppliers may still keep priority because they are often ordered
fallback sources for a specific external capability.

### Ability-Model Routing

`/admin/ability-models` is the model-call routing surface.

It answers:

```text
Which provider/model should this plugin or Cloud runtime ability use?
```

It may configure model binding, fallback model, timeout, retry, and operator
notes for supported routes. It does not define plugin abilities, prompt text,
router rules, WordPress switches, approval behavior, or final writes.

Plugin-oriented routes and Cloud-owned runtime dependencies are separated so
operators can configure actual model calls without mistaking read-only runtime
projections for another control plane.

### Model Reference Metadata

`models.dev` is used as reference metadata only.

It can enrich rows with:

- capability family;
- context and output limits;
- token price estimates;
- model aliases and series;
- deprecation or availability hints.

It is not billing truth, routing truth, provider credential truth, or usage
meter truth. Prices are displayed as reference estimates and normalized to
`per 1M tokens`.

Provider-visible upstream catalogs still decide which models can be enabled on
a provider channel. Reference metadata only makes those rows easier to inspect.

### Environment Variable Retirement

AI provider configuration is no longer intended to live in `.env.local`.

Environment-backed provider values were treated as one-time migration inputs.
The durable operating path is DB-managed provider connections through the
admin UI, with credentials masked and never returned to the browser.

## UI Decisions

The operator UI was repeatedly simplified around scanning and safe action:

- the Provider Management header no longer carries large metric blocks;
- supplier tabs were reduced to `Model suppliers` and `Capability suppliers`;
- inner duplicated tabs and repeated helper text were removed;
- model supplier rows use a compact table instead of cards;
- model supplier status filtering reads `All statuses`;
- enabled model counts show compact values such as `7` or `7 models` instead of
  repeating `enabled models` in every row;
- provider base URL and model-name previews are not shown in the default model
  supplier list;
- configuration detail and rarely changed connection fields are folded behind
  explicit disclosures;
- action columns are centered and use consistent button sizes;
- delete is a row-local two-step action: `Delete` -> `Confirm delete / Cancel`;
- normal ready/configured states are visually quiet, while missing credentials
  and disabled states remain scannable.

The provider channel dialog is now optimized around model visibility:

- basic connection details are collapsed by default when editing;
- upstream model sync and model reference update are grouped as low-frequency
  operations;
- search is represented by input placeholder and table filters, not redundant
  labels;
- capability and visibility filters stay near the model table;
- price unit text is held in the column header rather than repeated per row.

## Important Decisions To Preserve

1. Do not put provider priority on model suppliers.
   Priority belongs in ability/model routing or fallback choice, not in the
   provider connection list.

2. Do not duplicate capability supplier pages.
   Search, image source, rerank, and vector store providers should stay under
   Provider Management.

3. Do not turn model intelligence into routing automation.
   Reference metadata is useful for operators, but routing remains explicit.

4. Do not expose provider secrets to the browser.
   Credential fields may accept replacement values, but saved secrets remain
   masked.

5. Do not expose Cloud internals as default operator choices.
   Profile ids, instance ids, workflow metadata, and raw config ids belong in
   internal details or diagnostics.

## Verification Used In This Stage

Focused frontend gates:

```bash
node tests/unit/admin-ai-resources-contract.mjs
node tests/unit/admin-portal-i18n-completeness-contract.mjs
pnpm run frontend:type-check
git diff --check -- frontend/src/app/admin/ai-resources/page.tsx frontend/tests/unit/admin-ai-resources-contract.mjs frontend/src/lib/i18n.ts
```

Broader gates should be run before release promotion:

```bash
pnpm run check:fast
pnpm run check:seam
```

## Next Practical Follow-Up

The current stage is good enough for internal operator use.

The next useful work should be small and verification-oriented:

1. smoke-test `/admin/ai-resources` with real DeepSeek, MiniMax, and one
   OpenAI-compatible provider;
2. verify that enabled model counts and model reference metadata match the
   operator's mental model;
3. test destructive delete with one disposable provider connection;
4. run the broader fast gate before merging or release promotion.
