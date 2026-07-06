# Writing Assistance Evidence Loop History - June 2026

Status: project history and implementation summary.

This document records the product and engineering decisions made while shaping
Cloud-managed Site Knowledge, Cloud Web Search evidence, and the WordPress
Toolbox surfaces that consume them. It is intentionally a history document, not
a new control plane or runtime contract.

## Product Direction

The current writing product is not an autonomous article writer. It is a
writing-assistance system that helps an editor find evidence, context,
duplicates, gaps, internal links, candidate FAQ material, and current external
sources before a human writes or approves final content.

The fixed product posture is:

- Cloud can run expensive evidence work: chunking, embedding, vector storage,
  search, rerank, provider search, status, quotas, and diagnostics.
- WordPress remains the control plane for settings, abilities, approval,
  editing, publishing, and final writes.
- Outputs remain `suggestion_only`.
- Runtime responses always keep `direct_wordpress_write=false`.
- Cloud must not become a second ability registry, workflow registry, router
  truth, prompt/preset truth, OpenClaw truth, or WordPress write owner.

## What Was Built

### Cloud Site Knowledge

Cloud accepts the static managed runtime abilities:

- `npcink-cloud/site-knowledge-search`
- `npcink-cloud/site-knowledge-status`
- `npcink-cloud/site-knowledge-sync`

The matching contracts are:

- `site_knowledge_search.v1`
- `site_knowledge_status.v1`
- `site_knowledge_sync.v1`

Site Knowledge indexes bounded public WordPress sources sent by the local
WordPress side. The first source types are public posts and pages; approved
public comments can be included only when the Cloud comments-indexing setting
is enabled. Source rows and chunks are isolated by `site_id`.

The initial backend supports the existing Cloud stack:

- FastAPI runtime API
- PostgreSQL durable truth and read models
- Redis-assisted worker wakeup
- existing runtime worker for long sync runs
- SQLAlchemy and Alembic schema evolution

The vector backend is swappable behind the Site Knowledge backend interface.
For validation, Zilliz Cloud can be used with Cloud-managed credentials and
`BAAI/bge-m3` embeddings through a Cloud-managed embedding provider. DashVector
can be added later behind the same contract without changing WordPress-side
settings or ability names.

`site_knowledge_status.v1` and `site_knowledge_sync.v1` responses include an
`ownership` block and a `truth_boundaries` block. Cloud is the owner for Site
Knowledge index execution, index lifecycle, freshness policy, vector storage,
embedding execution, and diagnostics detail. The Cloud Addon remains the
WordPress-side delivery bridge for public change hints, while source content,
local approval, final write authority, and WordPress writes remain with the
local WordPress host. These fields are response metadata only; they do not add a
Cloud ability registry, workflow registry, WordPress control plane, or direct
write path.

### Cloud Web Search Evidence

Cloud Web Search provides external-web evidence through the hosted runtime
surface. It now supports both the original Cloud ability name and the current
Npcink alias:

- `npcink-cloud/web-search`
- `npcink-cloud/web-search`

The runtime contract remains `web_search.v1`. The normalized output includes a
`search_evidence_pack.v1` object so writing flows can consume structured source
cards, citation candidates, evidence gate status, and intent-specific guidance
without treating search results as final content.

Supported writing-relevant intents include background research, fact checking,
news, writing context, competitor research, pricing snapshots, product
comparison, source discovery, and external link candidates.

### Toolbox Surfaces

Toolbox keeps the WordPress-side user experience simple:

- Site Knowledge has one primary action: start an index when empty, refresh the
  index when content already exists.
- Status refresh stays in the status area.
- Search check is a verification surface, not a provider-settings surface.
- Vector provider keys, embedding dimensions, collection names, and endpoint
  settings are not shown or stored locally.
- Search and vector provider configuration stay Cloud-managed.

The UI now keeps users informed while Cloud is still processing:

- request send: `Sending index request...`
- queued refresh: `Index refresh queued...`
- active Cloud work: `Indexing in Cloud...`
- status copy warns that search results may remain stale until the index is
  ready.

This prevents a user from seeing a successful request and assuming that the
search index has already incorporated the latest WordPress changes.

## Why Deleted Or Stale Content Appeared During Testing

The observed stale/deleted search results were not a WordPress write-boundary
problem. They were index lifecycle and search semantics issues:

- a refresh request can be accepted before the worker finishes indexing;
- semantic vector search can return related content even when the exact query
  phrase is absent;
- an already indexed post remains searchable until a rebuild/delete/refresh run
  removes or supersedes its chunks;
- WordPress trash/deletion changes must be sent to Cloud through the sync path,
  because Cloud does not inspect or mutate WordPress directly.

The current mitigation is:

- show queued/running state clearly in Toolbox;
- treat existing index refresh as a Cloud rebuild when appropriate;
- filter search result display toward exact evidence when the UI is validating
  a literal query;
- keep delete/rebuild semantics in Cloud while the local side decides when to
  send changed public sources.

## Writing Workflows Enabled

The current evidence loop can support these practical writing-assistance
scenarios:

- site-grounded answer/source lookup;
- duplicate or overlap checks before writing;
- related-content and internal-link suggestions;
- stale-content refresh candidates;
- FAQ candidate discovery;
- content gap review;
- writer context enrichment;
- pre-draft writing support;
- external background/source packs;
- fact-check or pricing/current-claim preflight.

These flows should produce evidence, tasks, suggested uses, and local handoff
metadata. They should not produce full article bodies, ready-to-publish content,
automatic publishing instructions, article titles, SEO copy, or direct
WordPress write actions from Cloud Site Knowledge.

## Ability Consumption

AI callers, Toolbox fixed buttons, and OpenClaw-like natural-language channels
can consume the same bounded abilities and runtime outputs:

- Toolbox exposes the WordPress-side ability contracts.
- Cloud executes the managed runtime work.
- Returned artifacts include composition roles, evidence gates, handoff hints,
  and `suggestion_only` write posture.
- Local Core/WordPress remains responsible for proposals, approval, audit, and
  final object mutation.

This keeps OpenClaw and fixed Toolbox surfaces aligned without adding a second
Cloud ability registry or workflow engine.

## Provider And Secret Decisions

Cloud operators configure provider credentials centrally. WordPress users do
not provide search, embedding, rerank, vector database, or provider keys.

Current China-oriented validation choices:

- vector validation backend: Zilliz Cloud;
- likely future backend option: Alibaba Cloud DashVector;
- embedding model: `BAAI/bge-m3`, 1024 dimensions, good for Chinese, English,
  mixed-language, and longer text;
- optional rerank provider: Jina rerank, Cloud-managed only;
- external web search providers remain Cloud-managed.

Do not place real API keys, tokens, usernames, passwords, provider secrets, raw
embeddings, raw chunks, request headers, or full sensitive runtime payloads in
docs, fixtures, logs, or smoke evidence.

## Limits And Operational Guardrails

Large sites can have tens or hundreds of thousands of posts, so Cloud must
index in batches rather than trying to process an entire site in one request.

Current guardrails include:

- per-run document limits;
- per-run chunk limits;
- per-site indexed document limits;
- per-site indexed chunk limits;
- bounded query and document content lengths;
- quota status in Site Knowledge status responses;
- explicit Site Knowledge owner/truth fields in status and sync responses;
- existing runtime run concurrency limits;
- existing worker/runtime offload instead of adding Temporal, Celery, Kafka,
  RabbitMQ, NATS, or Kubernetes-first infrastructure.

For low-traffic WordPress sites, production deployments should still ensure
WordPress cron is triggered reliably, for example through server cron hitting
`wp-cron.php`, so automatic change detection and sync requests do not wait for
admin page visits.

## Next Work

The next useful work should stay small:

- keep Site Knowledge status/progress visible and calm for users;
- improve local change detection for posts, pages, comments, trash, restore,
  publish, update, and delete events;
- keep batching/debounce behavior conservative so busy sites do not spam Cloud;
- add Cloud detail visibility for indexed document counts, chunk counts,
  limits, and last run status;
- continue making the first writing-assistance flows useful before adding
  heavier ontology or graph features.

The long-term direction is "vector first, then lightweight ontology": use vector
evidence to reduce hallucination first, then add small read models for topics,
entities, FAQs, internal relationships, and taxonomy mappings only after the
basic evidence loop is stable.
