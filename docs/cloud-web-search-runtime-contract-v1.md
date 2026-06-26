# Cloud Web Search Runtime Contract v1

Status: MVP.

Cloud-managed Web Search is a hosted runtime evidence service. It lets the
WordPress side request external web results through the existing signed runtime
surface without sending customer provider keys to Cloud and without allowing
Cloud to write WordPress content.

## Runtime Ability

Cloud accepts these static managed ability names:

- `npcink-cloud/web-search`
- `npcink-cloud/web-search`

The matching contract version is:

- `web_search.v1`

When Toolbox or the Cloud Addon omits generic runtime routing fields, Cloud
normalizes this managed request to:

- `profile_id`: `web-search.managed`
- `execution_kind`: `web_search`
- `ability_family`: `knowledge`
- `data_classification`: `public`

This is a static runtime ingress compatibility path, not a Cloud ability
registry.

Admin and Portal display metadata for the matching preflight workflow is sourced
from the Cloud read-only Agent/Workflow metadata registry as
`external_web_evidence_preflight`. That metadata is UI/detail projection only; it
does not change runtime routing or create a Cloud workflow truth.

## Boundaries

- Results are always `suggestion_only`.
- Responses always include `direct_wordpress_write: false`.
- Cloud may call configured upstream search providers, normalize results,
  score evidence, meter usage, and expose read-only operational summaries.
- WordPress remains the final owner for inserting links, drafting, updating, or
  publishing content.
- Runtime requests must not include provider API keys, request headers,
  WordPress credentials, or final-write controls.
- Cloud must not return provider keys, Cloud secrets, WordPress credentials,
  request headers, or full sensitive request payloads.

## Cloud-Managed Providers

MVP provider support is Cloud-owned and configured by Cloud operators through
`/admin/ai-resources` using DB-managed provider connections. Search providers
use `kind=web_search_provider`; URL reader enhancement uses the same provider
connection path.

Supported built-in provider IDs:

- `tavily`
- `bocha`
- `apify`
- `jina_reader`
- `zhihu`

Provider credentials must be stored as provider connection secrets. Runtime
requests must never carry provider API keys. Secrets are encrypted at rest and
returned to admin browsers only as masked configured/missing status.

The retired `/admin/web-search` page and
`/internal/service/admin/web-search-providers` env-writer API are not the
operator path anymore. New changes should use the provider connection CRUD
surface instead:

- `GET /internal/service/admin/provider-connections`
- `POST /internal/service/admin/provider-connections`
- `PATCH /internal/service/admin/provider-connections/{connection_id}`
- `DELETE /internal/service/admin/provider-connections/{connection_id}`
- `POST /internal/service/admin/provider-connections/{connection_id}/test`

The runtime may still project DB provider connections onto legacy in-process
settings fields while the search adapters are being simplified. That bridge is
an implementation detail, not a supported env configuration surface.

The WordPress-side search key path is intentionally removed from Toolbox. The
default customer path uses Cloud-managed search.

## Input Shape

```json
{
  "ability_name": "npcink-cloud/web-search",
  "contract_version": "web_search.v1",
  "execution_pattern": "inline",
  "storage_mode": "result_only",
  "timeout_seconds": 20,
  "input": {
    "contract_version": "web_search.v1",
    "query": "latest WordPress AI search trends",
    "intent": "general_research",
    "provider": "auto",
    "max_results": 5,
    "recency_days": 7,
    "language": "en",
    "region": "US",
    "allowed_domains": [],
    "blocked_domains": [],
    "enhance_with_reader": false,
    "evidence_policy": {
      "min_score": 0,
      "required_sources": 1,
      "no_hit_policy": "abstain"
    },
    "write_posture": "suggestion_only"
  }
}
```

Supported first intents:

- `general_research`
- `article_background`
- `fact_check`
- `news`
- `writing_context`
- `competitor_research`
- `pricing_snapshot`
- `product_comparison`
- `source_discovery`
- `external_links`
- `zhihu_global_search`
- `zhihu_research`
- `zhihu_hot_topics`
- `zhida_simple`
- `zhida_deep`
- `zhida_deepsearch`

`zhihu_global_search` is the Zhihu Open Platform full-web search lane, not the
generic Tavily/Bocha/Apify provider pool. Toolbox or other local callers may
use a fixed managed source request:

```json
{
  "intent": "zhihu_global_search",
  "provider": "zhihu",
  "source_type": "zhihu_global_search",
  "write_posture": "suggestion_only"
}
```

Cloud normalizes this lane into `source_evidence.v1`. It is useful for
high-trust external evidence, citation candidates, current facts, and comparison
material. The default upstream path is the official Zhihu content endpoint:

```json
{
  "method": "GET",
  "path": "/api/v1/content/global_search",
  "query": {
    "Query": "AI 写作事实核查",
    "Count": 5
  }
}
```

When `recency_days` is supplied, Cloud may add the same date filter shape used
by the Zhihu playground: `publish_time>=YYYY-MM-DD AND publish_time<=YYYY-MM-DD`.

`zhihu_research` is a first-version pre-writing research lane. Toolbox may use a
fixed managed source request:

```json
{
  "intent": "zhihu_research",
  "provider": "zhihu",
  "source_type": "zhihu_research",
  "write_posture": "suggestion_only"
}
```

This is not a generic provider router exposed to WordPress. It asks Cloud to call
the configured Zhihu Open Platform source and normalize topic, question, author,
and engagement signals as source candidates for the current query. Hot-list
lookup is opt-in and should be displayed as a separate product section when used,
not mixed into current-topic results by default. The caller must treat the result
as pre-writing evidence only: no copying source text, no automatic rewriting into
an article, no publishing, and no WordPress write authority.

The default upstream request shape is:

```json
{
  "method": "GET",
  "path": "/api/v1/content/zhihu_search",
  "query": {
    "Query": "AI 写作准备",
    "Count": 5
  }
}
```

`zhihu_hot_topics` is a separate topic-pool lane. Toolbox may use a fixed managed
source request:

```json
{
  "intent": "zhihu_hot_topics",
  "provider": "zhihu",
  "source_type": "zhihu_hot_list",
  "write_posture": "suggestion_only"
}
```

Cloud may serve this lane from a server-side TTL cache. Hot topics are trend
signals only; callers must not treat them as verified facts, generated article
plans, or WordPress write instructions. A user should pick a topic manually, then
run focused Zhihu research or broader web verification before drafting.

The default upstream request shape is:

```json
{
  "method": "GET",
  "path": "/api/v1/content/hot_list",
  "query": {
    "Limit": 20
  }
}
```

`zhida_simple`, `zhida_deep`, and `zhida_deepsearch` are Zhihu direct-answer
lanes. Toolbox or other local callers may use fixed managed source requests:

```json
{
  "intent": "zhida_deep",
  "provider": "zhihu",
  "source_type": "zhida_deep",
  "write_posture": "suggestion_only"
}
```

Cloud normalizes these lanes into `grounded_answer.v1`. The answer text is a
reviewable preview only. It may support FAQ/AEO answers, short answer previews,
or research conclusion previews, but it must not be inserted as final article
text or published without the local/Core review path.

The default upstream request shape is:

```json
{
  "method": "POST",
  "path": "/v1/chat/completions",
  "body": {
    "model": "zhida-thinking-1p5",
    "messages": [
      {
        "role": "user",
        "content": "AI 写作前应该准备什么？"
      }
    ],
    "stream": false
  }
}
```

Mode-to-model mapping follows the public playground bundle:

| Cloud source type | Zhihu mode | Playground model |
| --- | --- | --- |
| `zhida_simple` | `simple` | `zhida-fast-1p5` |
| `zhida_deep` | `deep` | `zhida-thinking-1p5` |
| `zhida_deepsearch` | `deepsearch` | `zhida-agent` |

Cloud keeps compatibility with explicitly configured legacy or playground proxy
paths, but the default configuration uses the official Bearer-auth endpoints:
`/api/v1/content/zhihu_search`, `/api/v1/content/global_search`,
`/api/v1/content/hot_list`, and `/v1/chat/completions`.

## Atomic Output Contracts

The search runtime is the shared execution lane for four product-level atomic
capabilities:

| Atomic capability | Runtime source | Output contract | Product use |
| --- | --- | --- | --- |
| Global web search | Cloud-managed search providers or Zhihu full-web search | `source_evidence.v1` | External facts, citation candidates, competitor or product context |
| Zhihu search | Cloud-managed Zhihu search | `source_evidence.v1` plus optional `topic_candidate.v1` | Audience questions, viewpoints, objections, and citation candidates |
| Hot list | Cloud-managed Zhihu hot-list cache | `topic_candidate.v1` plus supporting `source_evidence.v1` | Daily topic pool and trend signals |
| Direct answer | Cloud-managed Zhihu direct-answer lanes or downstream answer composer over accepted evidence | `grounded_answer.v1` | Short answer preview, FAQ/AEO draft, or research conclusion preview |

This runtime returns `atomic_outputs` as an additive projection:

- `source_evidence`: normalized source cards under `source_evidence.v1`;
- `topic_candidates`: topic-selection candidates under `topic_candidate.v1`;
- `grounded_answer`: a `grounded_answer.v1` placeholder with
  `status=not_generated`, or a reviewable direct-answer preview when a
  configured direct-answer lane is called.

The direct-answer atom must stay suggestion-only. Even when Cloud receives
answer text from Zhihu direct answer, Web Search must not turn provider text into
a final article, draft insertion, or publishable WordPress write. This keeps
provider execution in Cloud while product composition, approval, and WordPress
writes remain local.

## Automatic Search Preflight

Generic hosted runtime requests may ask Cloud to automatically run Web Search
before the model/provider execution. This is intentionally semi-automatic:
Cloud does not inspect every prompt and decide to browse. A caller must declare
that external evidence is needed.

Supported input controls:

```json
{
  "requires_external_evidence": true,
  "topic": "latest WordPress AI search trends",
  "search_policy": {
    "mode": "auto",
    "intent": "news",
    "provider": "auto",
    "max_results": 3,
    "recency_days": 7,
    "enhance_with_reader": false,
    "evidence_policy": {
      "required_sources": 1,
      "no_hit_policy": "abstain"
    }
  }
}
```

`search_policy.mode` values:

- `off`: do not run automatic search.
- `auto`: run search only for external-evidence intents such as `news`,
  `fact_check`, `writing_context`, `competitor_research`, `source_discovery`,
  or `external_links`.
- `required`: run search and fail the runtime request if search fails.
- `dry_run`: report that search would run, but do not call a provider.

The search query is resolved from `search_policy.query`, `search_query`,
`query`, `topic`, `title`, or `headline`, in that order.

When automatic search succeeds, Cloud injects the normalized Web Search result
into provider input under:

```json
{
  "cloud_evidence": {
    "web_search": {
      "source": "cloud_managed_automatic_web_search",
      "report": {},
      "result": {}
    }
  }
}
```

The terminal runtime result also includes `automatic_web_search` so callers can
see whether search was skipped, dry-run, failed, or used. This evidence remains
`suggestion_only`; Cloud still must not write WordPress content.

## Output Shape

```json
{
  "artifact_type": "web_search_results",
  "composition_role": "external_web_evidence",
  "status": "ready",
  "provider": "tavily",
  "intent": "general_research",
  "query_hash": "sha256...",
  "query_chars": 36,
  "output_contract": "search_evidence_pack.v1",
  "evidence_gate": {
    "status": "passed",
    "min_score": 0,
    "required_sources": 1,
    "source_count": 3,
    "no_hit_policy": "abstain",
    "allows_web_grounded_assertion": true,
    "guidance": "Use returned web sources as external grounding evidence."
  },
  "results": [
	    {
	      "title": "Example result",
	      "url": "https://example.com/result",
	      "snippet": "Short provider-normalized snippet.",
	      "score": 0.91,
	      "source": "tavily",
	      "suggested_use": "external_research",
	      "write_posture": "suggestion_only",
	      "direct_wordpress_write": false
	    }
  ],
  "evidence_pack": {
    "artifact_type": "search_evidence_pack",
    "contract_version": "search_evidence_pack.v1",
    "pack_type": "external_research",
    "intent": "general_research",
    "status": "passed",
    "query_hash": "sha256...",
    "result_count": 1,
    "source_count": 1,
    "required_sources": 1,
    "provider": "tavily",
    "sections": [
      "external_sources",
      "citation_candidates",
      "risk_notes"
    ],
    "source_cards": [
      {
        "title": "Example result",
        "url": "https://example.com/result",
        "snippet": "Short provider-normalized snippet.",
        "source": "tavily",
        "suggested_use": "external_research",
        "citation_candidate": true,
        "write_posture": "suggestion_only",
        "direct_wordpress_write": false
      }
    ],
    "citation_candidates": [
      {
        "title": "Example result",
        "url": "https://example.com/result",
        "snippet": "Short provider-normalized snippet.",
        "source": "tavily",
        "suggested_use": "external_research",
        "citation_candidate": true,
        "write_posture": "suggestion_only",
        "direct_wordpress_write": false
      }
    ],
    "guidance": "Use returned web sources as external grounding evidence. Keep conclusions suggestion-only.",
    "write_posture": "suggestion_only",
    "direct_wordpress_write": false
  },
  "atomic_outputs": {
    "artifact_type": "atomic_knowledge_outputs",
    "contract_versions": [
      "grounded_answer.v1",
      "source_evidence.v1",
      "topic_candidate.v1"
    ],
    "source_evidence": {
      "artifact_type": "source_evidence_set",
      "contract_version": "source_evidence.v1",
      "status": "passed",
      "items": []
    },
    "topic_candidates": {
      "artifact_type": "topic_candidate_set",
      "contract_version": "topic_candidate.v1",
      "status": "empty",
      "items": []
    },
    "grounded_answer": {
      "artifact_type": "grounded_answer_preview",
      "contract_version": "grounded_answer.v1",
      "status": "not_generated",
      "answer_text": "",
      "source_refs": []
    }
  },
  "sources": [
    {
      "title": "Example result",
      "url": "https://example.com/result",
      "source": "tavily"
    }
  ],
  "write_posture": "suggestion_only",
  "direct_wordpress_write": false
}
```

`search_evidence_pack.v1` is an additive structured evidence artifact. It is
not a new workflow registry, not a publication plan, and not a WordPress write
instruction. It groups normalized source cards and citation candidates so local
writing surfaces can review current external evidence before a human writes or
approves final content.

For `zhihu_research` and `zhihu_hot_topics`, source cards may additionally
include `content_type`, `content_id`, `author_name`, `comment_count`,
`vote_up_count`, `authority_level`, `edit_time`, and `thumbnail_url` when the
upstream source returns them. These fields support review and prioritization
only; they must not be interpreted as permission to republish or as verified
factual truth.

## Site Knowledge Composition

Web Search is external-web evidence. Site Knowledge remains site-owned evidence
through `npcink-cloud/site-knowledge-search`. Product flows should combine
them explicitly:

- time-sensitive external facts: Web Search first
- site-specific assertions: Site Knowledge first
- article generation preflight: duplicate/refresh Site Knowledge plus external
  Web Search when current facts or sources are needed

If the evidence gate returns `insufficient_evidence`, AI callers must not state
time-sensitive or external facts as verified by web search.
