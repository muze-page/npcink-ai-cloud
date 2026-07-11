# Site Knowledge Runtime Contract v1

Status: MVP.

Cloud-managed Site Knowledge is a hosted runtime detail service. It indexes
bounded public WordPress content that the local WordPress side sends through the
Cloud Addon runtime client. It does not register WordPress abilities, own a
workflow registry, or write WordPress content.

## Runtime Abilities

The Cloud runtime accepts these static managed ability names:

- `npcink-cloud/site-knowledge-search`
- `npcink-cloud/site-knowledge-status`
- `npcink-cloud/site-knowledge-sync`

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
- Site Knowledge is a writing-assistance evidence service. It helps writers
  find context, citations, gaps, duplicates, internal links, FAQ candidates,
  and refresh candidates; it must not produce ready-to-publish article content.
- Cloud may chunk, embed, store, search, rerank, and report status for public
  site knowledge.
- Public `post` and `page` sources may be indexed by default. Public approved
  comments may be indexed only when Cloud explicitly enables comment indexing.
- Cloud must not publish, update, delete, or otherwise mutate WordPress content.
- Cloud must not return article bodies, article titles, SEO copy,
  `article_write_plan` candidates, full article drafts, ready-to-publish
  content, or automatic publishing instructions from Site Knowledge.
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

Cloud-managed provider settings:

- Embedding suppliers are DB-managed provider connections with
  `kind=embedding_provider`.
- Rerank suppliers are DB-managed provider connections with
  `kind=rerank_provider`.
- Vector store suppliers are DB-managed provider connections with
  `kind=vector_store_provider`.
- Provider credentials must be managed in `/admin/ai-resources`, not in
  `.env.local` provider keys.

Supported built-in vector-related provider IDs:

- `siliconflow` embedding provider, commonly with `BAAI/bge-m3`
- `openai` embedding provider
- `tei` embedding provider
- `jina` rerank provider, commonly with `jina-reranker-v3`
- `zilliz` vector store provider

The following remain environment-controlled runtime guardrails, because they
bound workload shape rather than identify a provider secret:

- `NPCINK_CLOUD_SITE_KNOWLEDGE_COMMENTS_ENABLED`: default `false`; when true,
  Cloud may index approved public comments supplied by WordPress.
- `NPCINK_CLOUD_SITE_KNOWLEDGE_MAX_SYNC_DOCUMENTS_PER_RUN`: default `500`.
  Limits how many public documents or comments one sync run may index.
- `NPCINK_CLOUD_SITE_KNOWLEDGE_MAX_SYNC_CHUNKS_PER_RUN`: default `5000`.
  Limits how many chunks one sync run may embed and write.
- `NPCINK_CLOUD_SITE_KNOWLEDGE_MAX_INDEXED_DOCUMENTS_PER_SITE`: default
  `10000`. Protects per-site storage and provider cost for very large sites.
- `NPCINK_CLOUD_SITE_KNOWLEDGE_MAX_INDEXED_CHUNKS_PER_SITE`: default
  `200000`. This is the main vector storage guardrail.
- `NPCINK_CLOUD_SITE_KNOWLEDGE_QUOTA_WARNING_RATIO`: default `0.85`.
  Status returns `near_limit` once document or chunk utilization reaches this
  ratio.
- `NPCINK_CLOUD_SITE_KNOWLEDGE_RERANK_TOP_K`: default `30`
- `NPCINK_CLOUD_SITE_KNOWLEDGE_RERANK_TIMEOUT_SECONDS`: default `8`
- `NPCINK_CLOUD_SITE_KNOWLEDGE_ZILLIZ_TIMEOUT_SECONDS`: default `10`

The runtime may project DB provider connections onto legacy in-process settings
fields while the Site Knowledge adapters are being simplified. That bridge is
an implementation detail, not a supported env credential surface.

The Zilliz adapter is intentionally behind a small backend interface. A later
DashVector migration should add a new backend implementation and preserve the
same runtime contracts, response shape, and WordPress write boundary.

The deterministic embedding provider exists for local tests and controlled
fallback only. The managed embedding provider paths use the existing Cloud
provider adapter boundary, so embedding endpoint credentials remain
Cloud-managed provider connection secrets and are not accepted from or returned
to WordPress.

Managed embedding provider calls are runtime-governed provider calls. When
Site Knowledge uses TEI, OpenAI, SiliconFlow, or another Cloud-managed
embedding adapter, Cloud records provider-call telemetry and usage meter events
on the owning runtime run with `ability_family=knowledge` and
`execution_kind=knowledge` or `embedding` as appropriate. This keeps vector
capability quota, cost, and audit behavior aligned with text, image, and search
runtime profiles instead of creating a separate vector billing path.

## Large Site Quotas

Sites with tens or hundreds of thousands of public posts can be indexed over
time, but they must not be pushed through one request or one worker run.

Cloud enforces two layers:

- per-run caps: stop one `site-knowledge-sync` run from embedding too much at
  once;
- per-site caps: stop one connected site from consuming unbounded vector
  storage and provider quota.

When a sync hits a limit, Cloud returns `status=completed` with
`progress.stage=limited`, `sync.skipped_documents`, and
`sync.skipped_due_to_quota`. The response also includes a `quota` object with
the active limits and utilization. Skipped content remains WordPress-owned and
can be indexed by later batches after quota or plan policy changes.

`site-knowledge-status` includes `coverage.quota`:

```json
{
  "status": "ok|near_limit|limited|empty",
  "indexed_documents": 10000,
  "indexed_chunks": 180000,
  "max_indexed_documents_per_site": 10000,
  "max_indexed_chunks_per_site": 200000,
  "max_sync_documents_per_run": 500,
  "max_sync_chunks_per_run": 5000,
  "document_utilization": 1.0,
  "chunk_utilization": 0.9,
  "skipped_due_to_quota": 0
}
```

Toolbox should continue to expose simple start/refresh/status actions. It may
display this quota detail, but it must not store vector provider credentials or
become the quota control plane.

## Source Types

Post and page content is supplied through `documents`. Comments are supplied
through `comments` and are ignored unless
`NPCINK_CLOUD_SITE_KNOWLEDGE_COMMENTS_ENABLED=true`.

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
- `writing_context`: writer context enrichment. Results include
  `context_role`, `citation`, and `usage_guidance` so the local writing surface
  can show site-owned context before the writer drafts.
- `writing_support_plan`: writer preparation support. Results include
  `writing_support`, `pre_draft_tasks`, `evidence_source`,
  `planning_mode=wordpress_local_only`, and `blocked_outputs` so editors can
  move faster on source review, coverage decisions, internal links, and media
  follow-up without Cloud producing article titles, article bodies, SEO copy,
  `article_write_plan` candidates, full drafts, ready-to-publish content, or
  automatic publishing instructions.
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

## WordPress AI Generation Reference

The existing `npcink-cloud/wp-ai-connector` runtime may optionally use Site
Knowledge as hidden context for title, excerpt, meta description, summary, and
classification tasks. The WordPress-side connector must explicitly send the
task-bound mode:

```json
{
  "site_knowledge_reference": {
    "enabled": true,
    "mode": "site_title_style"
  }
}
```

The allowed task-to-mode mapping is:

- `title_generation` -> `site_title_style`
- `excerpt_generation` -> `site_excerpt_style`
- `meta_description` -> `site_meta_style`
- `content_summary` -> `site_summary_style`
- `content_classification` -> `site_taxonomy_history`

This is an additive runtime hint inside the existing scene request, not a new
ability, workflow, prompt registry, or Cloud-side preference truth. Cloud uses
the current scene prompt as a bounded `writing_context` query, then assembles an
internal `generation_context.v1` pack. The pack is provider-input detail only;
it is not accepted from callers and is not returned to WordPress AI users.

The internal task policies are deliberately bounded:

| Task | Minimum score | Source posts | References | Context characters |
| --- | ---: | ---: | ---: | ---: |
| title | 0.35 | 6 | 1 aggregate profile | 400 |
| excerpt | 0.35 | 5 | 1 aggregate profile | 400 |
| meta description | deferred | 0 | 0 | 0 |
| summary | deferred | 0 | 0 | 0 |
| classification | 0.35 | 8 | 20 terms | 1,200 |

Results are relevance-filtered, deduplicated by post, and checked for a strong
content-fingerprint overlap with the current scene before projection. Title and
excerpt generation receive only an aggregate profile calculated from related
historical samples: a qualitative short/medium/long preference, sentence shape,
and qualitative question-mark and colon usage. Exact sample counts, lengths,
and rates are not sent because models may mistake profile numbers for article
facts. The historical titles and excerpts
themselves are not placed in provider input. Classification receives only
bounded existing `category` and `post_tag` names stored as Site Knowledge
document metadata; repeated terms across related posts rank first. Source
chunks, raw style samples, scores, URLs, and evidence details are never placed
in the generation context or WordPress AI result.

Meta description and summary hints remain contract-valid for forward
compatibility but currently skip vector retrieval and fall back to ordinary
generation. Real A/B evidence showed that substituting ordinary post excerpts
for accepted SEO descriptions or accepted summaries distracts the model and is
not task-appropriate background. These tasks may be activated only after Site
Knowledge indexes a dedicated, provenance-safe source for that exact task and a
new paired quality gate passes.

The provider instruction may use aggregate title/excerpt length and punctuation
preferences, but it must not introduce facts absent from the current scene
input. Classification
history is candidate vocabulary only: it cannot invent term IDs, force a term,
or write taxonomy. Missing, insufficient, filtered, or unavailable Site
Knowledge silently falls back to ordinary generation. Bounded provider metadata
records only the context contract, status, reason, mode, reference count, and
character count for runtime quality diagnosis; it does not contain source text,
scores, URLs, or taxonomy details. The WordPress AI result remains the task's
ordinary reviewable result with `suggestion_only` posture and no WordPress write
authority.

The local Cloud Addon owns the enable/disable preference and transmits it on
each eligible request. Cloud does not persist or expose a second setting for
this preference.

## Agent Handoff

`site-knowledge-search` now returns an additive `agent_handoff` object. This is
the first bounded Agentic handoff shape for:

```text
site_knowledge -> suggestion_only -> local proposal
```

The handoff's static identity and boundary fields come from the Cloud read-only
Agent/Workflow metadata projection. Runtime evidence and proposal inputs remain
in the existing runtime result.

The handoff is not a new Cloud Agent platform, writable registry, route,
workflow truth, or WordPress write authority. It is a structured local handoff
hint embedded in the existing runtime result.

For proposal-capable intents, such as `content_gap_analysis`, `internal_links`,
`refresh_suggestions`, `faq_candidates`, `related_content`, `duplicate_check`,
and `writing_support_plan`, the handoff uses:

```json
{
  "agent_id": "site_knowledge_suggestion_agent",
  "agent_version": "site_knowledge_agent.v1",
  "handoff_type": "proposal_input",
  "handoff_owner": "wordpress_local",
  "requires_local_approval": true,
  "write_posture": "suggestion_only",
  "direct_wordpress_write": false,
  "proposal_input": {
    "source": "site_knowledge",
    "workflow": "content_gap_analysis",
    "cloud_output": "gap_evidence",
    "local_next_action": "review_content_gap_before_local_plan",
    "evidence_refs": []
  }
}
```

For read/display intents such as `site_search` and `writing_context`, the
handoff remains `suggestion_only` and `proposal_input` is empty.

`evidence_refs` intentionally carries compact source references, not full chunks
or raw provider payloads. Local Core may use it to construct or prefill a local
proposal, but final approval, preflight, audit, and WordPress writes remain
local.

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

## Real-Chain Smoke

Use the local real-chain smoke after configuring Cloud-managed vector settings
in `.env.local` or the deployment secret manager:

```bash
pnpm run smoke:site-knowledge
```

The smoke validates the running dev `api` and `worker` containers with the
current Cloud env:

- `zilliz_cloud` vector backend
- `BAAI/bge-m3` embeddings through the configured Cloud embedding provider
- queued `site-knowledge-sync` processed by the runtime worker
- inline `site-knowledge-search` with `evidence_gate.status=passed`
- inline `site-knowledge-status` reporting indexed chunks
- `suggestion_only` and `direct_wordpress_write=false`

Smoke evidence is written under `.tmp/site-knowledge-real-chain-smoke/` and must
not be committed. Evidence contains only redacted configuration and pass/fail
counts; it must not include provider keys, Cloud secrets, raw embeddings, query
text, or chunk text.
