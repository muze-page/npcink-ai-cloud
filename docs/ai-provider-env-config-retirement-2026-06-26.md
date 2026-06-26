# AI Provider Env Config Retirement - 2026-06-26

## Status

Accepted.

## Decision

AI provider channels are no longer configured through `.env.local` provider
keys. Daily provider operations use Cloud runtime storage through
`/admin/ai-resources` and the bounded provider connection endpoints:

- `GET /internal/service/admin/provider-connections`
- `POST /internal/service/admin/provider-connections`
- `PATCH /internal/service/admin/provider-connections/{connection_id}`
- `DELETE /internal/service/admin/provider-connections/{connection_id}`
- `POST /internal/service/admin/provider-connections/{connection_id}/test`

The previous environment import endpoint is retired:

- `POST /internal/service/admin/provider-connections/import-env`

The previous MiniMax-specific environment settings surface is retired:

- `GET /internal/service/admin/audio-providers`
- `POST /internal/service/admin/audio-providers`
- `POST /internal/service/admin/audio-providers/minimax/test`

MiniMax, OpenAI-compatible, Anthropic, OpenRouter, SiliconFlow, LiteLLM, vLLM,
TEI, web search providers, image-source providers, embedding providers, rerank
providers, vector-store providers, and other runtime supplier channels should
be added as provider connections instead. Secrets stay encrypted at rest and
are returned to browsers only as masked status.

The retired env-backed capability supplier APIs are no longer operator paths:

- `GET /internal/service/admin/web-search-providers`
- `POST /internal/service/admin/web-search-providers`
- `GET /internal/service/admin/image-source-providers`
- `POST /internal/service/admin/image-source-providers`

## Boundary

This does not make Cloud a WordPress control plane. Cloud owns provider runtime
connection detail, diagnostics, and execution readiness only.

Cloud still must not own:

- WordPress writes
- approval or preflight truth
- ability registry truth
- workflow registry truth
- prompt, router, or preset truth

## Migration Notes

Local developer machines that previously had OpenAI, MiniMax, search,
image-source, embedding, rerank, or vector-store values in `.env.local` should
import or recreate those providers through `/admin/ai-resources`, then remove
the old environment keys.

For local verification, check that:

- `.env.local` has no `NPCINK_CLOUD_OPENAI_*` provider key values.
- `.env.local` has no `NPCINK_CLOUD_MINIMAX_*` provider key values.
- `.env.local` has no `NPCINK_CLOUD_WEB_SEARCH_*` provider key values.
- `.env.local` has no `NPCINK_CLOUD_IMAGE_SOURCE_*` provider key values.
- `.env.local` has no provider credential values for Site Knowledge embedding,
  rerank, or vector-store suppliers.
- `/admin/ai-resources` shows the corresponding DB provider connections as
  configured.
- `/admin/audio-providers` is no longer a provider configuration entry.
- `/admin/web-search` and `/admin/image-sources` are no longer provider
  configuration entries.

## Rationale

Keeping AI channels in `.env.local` made it unclear which feature used which
provider/model and created multiple operator paths for the same secret. Moving
provider operations into DB-managed provider connections gives one scannable
runtime source, masked credential state, explicit tests, and auditable admin
events without expanding Cloud into local WordPress governance.
