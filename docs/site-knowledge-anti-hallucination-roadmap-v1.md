# Site Knowledge Anti-Hallucination Roadmap v1

Status: MVP direction.

Cloud-managed Site Knowledge reduces hallucination by making site-owned evidence
the first step before AI workflows produce assertions, drafts, links, FAQ
candidates, refresh suggestions, or content gap analysis. The current sequence
is: vector first, then lightweight ontology.

## Boundary

- WordPress remains the local control plane and final write owner.
- Toolbox and the Cloud Addon may start sync, request status, and request search.
- Cloud may chunk, embed, index, search, rerank, score, and expose read-only
  status or observability details.
- Cloud must not publish, update, delete, or directly mutate WordPress content.
- All outputs remain `suggestion_only` with `direct_wordpress_write=false`.
- Provider keys, Cloud secrets, WordPress credentials, raw embeddings, and raw
  sensitive prompts must not be returned to WordPress or stored in fixtures.

## Phase 1: Vector Evidence Loop

Goal: prove the real chain before adding more knowledge abstractions.

Acceptance:

- One real WordPress site can run `rebuild`, `status`, and `search`.
- Public posts and pages are indexed by `site_id`.
- Approved comments are indexed only when Cloud enables comment indexing.
- Zilliz Cloud can store and search chunks using the configured Cloud embedding
  provider.
- Search results include source metadata, chunk excerpt, score, suggested use,
  and evidence gate status.
- No-hit and low-evidence responses instruct AI callers to abstain or disclose
  uncertainty instead of inventing site-specific facts.
- Cloud admin or portal observability shows indexed chunks, search count,
  no-hit rate, latency, and failure reasons without exposing chunk text,
  embeddings, query text, or secrets.

## Phase 2: Evidence Gate as Product Contract

Every AI workflow that consumes Site Knowledge should treat search as an
evidence preflight:

- `min_score`: minimum score for a result to count as grounding evidence.
- `required_sources`: minimum accepted source count before the caller may make a
  site-grounded assertion.
- `no_hit_policy`: default `abstain`; callers may explicitly choose
  `fallback_to_general` only when the UX labels the answer as not site-grounded.

If the evidence gate returns `insufficient_evidence`, the assistant should not
state site-specific facts. It should ask for more source material, return an
empty grounded answer, or use general knowledge with an uncertainty disclaimer
when the caller explicitly allowed that fallback.

## Phase 3: Lightweight Ontology

Do not introduce a graph database or second control plane in the first version.
Build lightweight Cloud read models only after the vector evidence loop is
stable:

- topic clusters
- entities such as products, people, brands, places, and terms
- FAQ candidates with source posts/comments
- content relationships such as related, duplicate, conflict, stale, or missing
- WordPress category/tag mappings to Cloud topic clusters

These read models are advisory. They may support recommendations, but final
edits and WordPress writes stay local.

## Deferred

- DashVector backend migration: add a backend implementation only after Zilliz
  validation is stable; preserve the same runtime contracts.
- Heavy ontology or knowledge graph: defer until vector evidence quality and
  operational metrics show a clear need.
- New orchestration infrastructure: do not add Temporal, Celery, Kafka,
  RabbitMQ, NATS, Kubernetes-first deployment, or a second scheduler/workflow
  truth.
