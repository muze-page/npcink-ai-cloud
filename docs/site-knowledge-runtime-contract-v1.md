# Site Knowledge Runtime Contract v1

Status: MVP.

Cloud-managed Site Knowledge is a hosted runtime detail service. It indexes
bounded public WordPress content that the local WordPress side sends through the
Cloud Addon runtime client. It does not register WordPress abilities, own a
workflow registry, or write WordPress content.

## Runtime Abilities

The Cloud runtime accepts these static managed ability names:

- `magick-ai-cloud/site-knowledge-search`
- `magick-ai-cloud/site-knowledge-status`
- `magick-ai-cloud/site-knowledge-sync`

The matching contract versions are:

- `site_knowledge_search.v1`
- `site_knowledge_status.v1`
- `site_knowledge_sync.v1`

When Toolbox omits generic runtime routing fields, Cloud normalizes these
managed requests to:

- `profile_id`: `site-knowledge.managed`
- `execution_kind`: `knowledge`
- `ability_family`: `knowledge`
- `data_classification`: `public_site_content`

This normalization is a static runtime ingress compatibility path, not a Cloud
ability registry.

## Boundaries

- Results are always `suggestion_only`.
- Responses always include `direct_wordpress_write: false`.
- Cloud may chunk, embed, store, search, rerank, and report status for public
  site knowledge.
- Public `post` and `page` sources may be indexed by default. Public approved
  comments may be indexed only when Cloud explicitly enables comment indexing.
- Cloud must not publish, update, delete, or otherwise mutate WordPress content.
- Cloud must not return provider keys, Cloud secrets, WordPress credentials,
  request headers, or full sensitive request payloads.
- Long `site-knowledge-sync` runs use the existing runtime worker path and
  `run_records`; no second queue, scheduler, or workflow engine is introduced.

## Vector Backend

The default MVP backend stores one Cloud-owned read model in PostgreSQL:

- `site_knowledge_documents`
- `site_knowledge_chunks`

Rows are isolated by `site_id`. Embeddings are stored as JSON for the MVP and
scored in Python with cosine similarity. This keeps the first version within
the existing FastAPI, PostgreSQL, Redis, SQLAlchemy, Alembic, and worker stack.

Cloud can switch the vector index to Zilliz Cloud for validation without any
Toolbox or WordPress-side settings. The WordPress side only sends bounded
`publish` public content and executes the managed Cloud abilities.

Cloud-managed settings:

- `MAGICK_CLOUD_SITE_KNOWLEDGE_VECTOR_BACKEND`: `postgres_json` or
  `zilliz_cloud`
- `MAGICK_CLOUD_SITE_KNOWLEDGE_EMBEDDING_PROVIDER`: `deterministic`, `tei`,
  `openai`, or `siliconflow`; production validation in China should use
  `siliconflow` with `BAAI/bge-m3`
- `MAGICK_CLOUD_SITE_KNOWLEDGE_EMBEDDING_MODEL`: default `BAAI/bge-m3`
- `MAGICK_CLOUD_SITE_KNOWLEDGE_EMBEDDING_DIMENSIONS`: default `1024`
- `MAGICK_CLOUD_SITE_KNOWLEDGE_VECTOR_METRIC_TYPE`: default `COSINE`
- `MAGICK_CLOUD_SITE_KNOWLEDGE_COMMENTS_ENABLED`: default `false`; when true,
  Cloud may index approved public comments supplied by WordPress.
- `MAGICK_CLOUD_SITE_KNOWLEDGE_ZILLIZ_URI`: required when `zilliz_cloud`
  is enabled
- `MAGICK_CLOUD_SITE_KNOWLEDGE_ZILLIZ_TOKEN`: required when `zilliz_cloud`
  is enabled
- `MAGICK_CLOUD_SITE_KNOWLEDGE_ZILLIZ_DATABASE`: optional
- `MAGICK_CLOUD_SITE_KNOWLEDGE_ZILLIZ_COLLECTION`: default
  `magick_site_knowledge_chunks`
- `MAGICK_CLOUD_SITE_KNOWLEDGE_ZILLIZ_TIMEOUT_SECONDS`: default `10`
- `MAGICK_CLOUD_TEI_PROVIDER_ENABLED`: `true` when
  `MAGICK_CLOUD_SITE_KNOWLEDGE_EMBEDDING_PROVIDER=tei`
- `MAGICK_CLOUD_TEI_BASE_URL`: Cloud-managed TEI or compatible embedding
  endpoint
- `MAGICK_CLOUD_TEI_API_KEY`: optional, only when the embedding endpoint
  requires it
- `MAGICK_CLOUD_TEI_MODEL_IDS`: must include `BAAI/bge-m3`
- `MAGICK_CLOUD_SILICONFLOW_PROVIDER_ENABLED`: `true` when
  `MAGICK_CLOUD_SITE_KNOWLEDGE_EMBEDDING_PROVIDER=siliconflow`
- `MAGICK_CLOUD_SILICONFLOW_BASE_URL`: default `https://api.siliconflow.cn/v1`
- `MAGICK_CLOUD_SILICONFLOW_API_KEY`: required when SiliconFlow embeddings are
  enabled; keep it only in Cloud deploy secrets
- `MAGICK_CLOUD_SILICONFLOW_TIMEOUT_SECONDS`: default `30`

The Zilliz adapter is intentionally behind a small backend interface. A later
DashVector migration should add a new backend implementation and preserve the
same runtime contracts, response shape, and WordPress write boundary.

The deterministic embedding provider exists for local tests and controlled
fallback only. The managed embedding provider paths use the existing Cloud
provider adapter boundary, so embedding endpoint credentials remain
Cloud-managed and are not accepted from or returned to WordPress.

## Source Types

Post and page content is supplied through `documents`. Comments are supplied
through `comments` and are ignored unless
`MAGICK_CLOUD_SITE_KNOWLEDGE_COMMENTS_ENABLED=true`.

Comment input must be bounded public data:

- `comment_id`
- `post_id`
- `comment_status`: `approved`, `approve`, or `1`
- `created_gmt`
- `url`
- `content_excerpt`
- `content_hash`

Cloud must not accept or store comment author email, IP address, user agent,
payment/contact identifiers, or WordPress credentials for Site Knowledge.

Stored chunks include:

- `source_type`: `post`, `page`, or `comment`
- `source_id`: post/page ID or comment ID
- `parent_post_id`: parent post ID for comments

Search defaults to `source_types=["post","page"]`. Callers must explicitly pass
`filters.source_types=["comment"]` or include `comment` in the list when a
workflow should use comments, such as FAQ or user-feedback analysis.

## Product Workflows

`site-knowledge-search` remains one runtime ability. Product workflows are
selected through `input.intent`; Cloud does not register additional abilities or
write WordPress content.

Supported first workflows:

- `site_search`: site content Copilot. Results include `answer_source`,
  `copilot_action`, and `response_mode` so an assistant can answer with
  source-grounded site references.
- `faq_candidates`: FAQ candidate mining from public content and explicitly
  requested approved comments. Results include `faq_candidate`,
  `suggested_action`, and `faq_mode=wordpress_local_only`.
- `related_content`: topic cluster planning. Results include
  `cluster_candidate`, `cluster_role`, `planning_action`, and
  `planning_mode=wordpress_local_only`.
- `content_gap_analysis`: content coverage review. Results include
  `gap_signal`, `suggested_action`, and `planning_mode=wordpress_local_only`
  so editors can decide whether to expand existing content or create new
  coverage.
- `duplicate_check`: publish preflight conflict review. Results include
  `duplicate_check` with risk, signals, and local review guidance before a
  draft is created or published.
- `writing_context`: generation context enrichment. Results include
  `context_role`, `citation`, and `usage_guidance` so the generation flow can
  cite site-owned context before drafting.
- `internal_links`: editor link recommendation. Results include
  `anchor_text_candidates`, `link_target`, `suggested_action`, and
  `insert_mode=wordpress_local_only`.
- `refresh_suggestions`: stale/overlapping content review. Results include
  `refresh_action`, `refresh_signals`, `suggested_action`, and
  `update_mode=wordpress_local_only`. The same results include
  `duplicate_check` so generation flows can warn before drafting when a similar
  article already exists.

All workflow metadata is advisory. WordPress still owns insertion, edits,
publishing, and final user confirmation.

## Evidence Gate

Search callers may pass an optional `evidence_policy` object:

```json
{
  "evidence_policy": {
    "min_score": 0.25,
    "required_sources": 1,
    "no_hit_policy": "abstain"
  }
}
```

Cloud applies the policy before returning results. Results below `min_score` do
not count as grounding evidence. The response includes:

```json
{
  "evidence_gate": {
    "status": "passed|insufficient_evidence",
    "min_score": 0.25,
    "required_sources": 1,
    "source_count": 1,
    "no_hit_policy": "abstain",
    "allows_site_grounded_assertion": true,
    "guidance": "Use returned site sources as grounding evidence."
  }
}
```

Default policy is `min_score=0.25`, `required_sources=1`, and
`no_hit_policy=abstain`. If the gate returns `insufficient_evidence`, AI
callers must not invent site-specific facts. They should abstain, ask for more
source material, return an empty grounded answer, or use general knowledge only
when the caller explicitly allowed a non-site-grounded fallback.

## Coverage Semantics

`post_type_coverage` is MVP Cloud-seen coverage. It reports coverage for post
types present in the Cloud index, not authoritative whole-site WordPress
coverage. Whole-site coverage requires the WordPress side to provide source
totals in a later contract.

## Anti-Hallucination Roadmap

The current implementation follows
[`site-knowledge-anti-hallucination-roadmap-v1.md`](site-knowledge-anti-hallucination-roadmap-v1.md):
first establish a real vector evidence loop, then add lightweight ontology read
models such as topic clusters, entities, FAQ candidates, content relationships,
and category/tag mappings. Heavy graph infrastructure and new orchestration
systems remain deferred.
