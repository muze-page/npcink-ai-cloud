# Provider Connection Production Runbook - 2026-06-30

Status: active operator runbook.

Purpose: configure the production supplier matrix through DB-managed provider
connections after provider environment configuration has been retired.

Boundary:

- Cloud owns provider runtime connection detail, readiness, diagnostics, and
  execution evidence.
- Cloud does not own WordPress writes, approval truth, ability registry truth,
  workflow registry truth, prompt/router/preset truth, or local governance.
- Supplier secrets must be entered through `/admin/ai-resources` provider
  connections. Do not put provider credentials back into `.env.deploy`,
  `.env.local`, deploy scripts, release docs, or shell command history.

## Current Gate

Run the full matrix gate on the production host:

```bash
cd /opt/npcink-ai-cloud/current
bash deploy/remote-provider-matrix-smoke.sh
```

The production matrix is not complete until these capabilities are present:

- `text_generation`
- `image_generation`
- `web_search`
- `image_source`
- `embedding`
- `vector_store`

When only the currently deployed text/image subset is expected, use:

```bash
cd /opt/npcink-ai-cloud/current
NPCINK_CLOUD_REQUIRED_PROVIDER_CAPABILITIES=text_generation,image_generation \
  bash deploy/remote-provider-matrix-smoke.sh
```

## Configure In Admin

Open `/admin/ai-resources`, create or edit provider connections, and use the
provider test action after each save. Credentials are masked in responses and
stored encrypted at rest.

Minimum field mapping:

| Capability | Connection ID | Provider ID | Kind | Base URL | Runtime Profile |
| --- | --- | --- | --- | --- | --- |
| Generic web search | `search_tavily` | `tavily` | `web_search_provider` | `https://api.tavily.com` | `web-search.managed` |
| Chinese/general web search | `search_bocha` | `bocha` | `web_search_provider` | `https://api.bochaai.com/v1` | `web-search.managed` |
| Actor-backed web search | `search_apify` | `apify` | `web_search_provider` | `https://api.apify.com/v2` | `web-search.managed` |
| Zhihu search | `search_zhihu` | `zhihu` | `web_search_provider` | `https://developer.zhihu.com` | `web-search.managed` |
| URL reader enhancement | `search_jina_reader` | `jina_reader` | `web_search_provider` | `https://r.jina.ai` | `web-search.reader` |
| Image source | `image_unsplash` | `unsplash` | `image_source_provider` | `https://api.unsplash.com` | `image-source.managed` |
| Embedding, API-hosted | `embedding_siliconflow` | `siliconflow` | `embedding_provider` | `https://api.siliconflow.cn/v1` | `embed.default` |
| Embedding, OpenAI-compatible | `embedding_openai` | `openai` | `embedding_provider` | upstream `/v1` URL | `embed.default` |
| Embedding, self-hosted TEI | `embedding_tei` | `tei` | `embedding_provider` | TEI base URL | `embed.default` |
| Vector store | `vector_zilliz` | `zilliz` | `vector_store_provider` | Zilliz URI | `site-knowledge.vector-store` |

Use at least one configured provider for each required capability. For search,
the supported primary providers are `search_tavily`, `search_bocha`,
`search_apify`, and `search_zhihu`; they all project to `web_search`, while
provider-specific requests can still select the matching provider. `search_jina_reader`
is optional URL reader enhancement and should not be counted as the primary
search provider.

## Config JSON Templates

Use these JSON objects in the provider connection config field as needed.
Omit empty optional keys rather than storing placeholders.

Tavily:

```json
{
  "provider_mode": "auto",
  "timeout_seconds": 15,
  "cost_per_query": 0
}
```

Bocha:

```json
{
  "provider_mode": "auto",
  "timeout_seconds": 15,
  "cost_per_query": 0
}
```

Apify:

```json
{
  "provider_mode": "auto",
  "actor_id": "apify/google-search-scraper",
  "timeout_seconds": 30,
  "cost_per_query": 0
}
```

Jina Reader:

```json
{
  "timeout_seconds": 15,
  "max_pages": 1,
  "cost_per_page": 0
}
```

Zhihu:

```json
{
  "provider_mode": "auto",
  "search_path": "/api/v1/content/zhihu_search",
  "global_search_path": "/api/v1/content/global_search",
  "hot_list_path": "/api/v1/content/hot_list",
  "direct_answer_path": "/v1/chat/completions",
  "timeout_seconds": 15,
  "cost_per_query": 0,
  "hot_list_cache_ttl_seconds": 3600
}
```

Image source:

```json
{
  "provider_mode": "auto",
  "timeout_seconds": 15,
  "cost_per_query": 0
}
```

Embedding:

```json
{
  "model_id": "BAAI/bge-m3",
  "dimensions": 1024
}
```

TEI embedding:

```json
{
  "model_id": "BAAI/bge-m3",
  "model_ids": "BAAI/bge-m3",
  "dimensions": 1024,
  "timeout_seconds": 12,
  "region": "self-hosted"
}
```

Zilliz vector store:

```json
{
  "uri": "https://example.zillizcloud.com",
  "database": "npcink",
  "collection": "site_chunks",
  "timeout_seconds": 10
}
```

## Closeout Checks

After saving and testing the connections:

```bash
cd /opt/npcink-ai-cloud/current
bash deploy/remote-provider-status.sh
bash deploy/remote-provider-matrix-smoke.sh
```

Expected closeout:

- matrix gate exits with status `0`;
- `missing_capabilities` is empty;
- provider truth is `db_managed_provider_connections`;
- secret exposure is `none`;
- runtime projection counts are non-zero for `web_search`, `image_source`,
  `embedding`, and `vector_store`;
- text and image runtime smoke still pass.

If the matrix gate fails only on `web_search`, `image_source`, `embedding`, or
`vector_store`, the missing item is a provider connection/configuration issue,
not a deploy issue.
