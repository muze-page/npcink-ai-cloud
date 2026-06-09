# Cloud Web Search Runtime Contract v1

Status: MVP.

Cloud-managed Web Search is a hosted runtime evidence service. It lets the
WordPress side request external web results through the existing signed runtime
surface without sending customer provider keys to Cloud and without allowing
Cloud to write WordPress content.

## Runtime Ability

Cloud accepts these static managed ability names:

- `magick-ai-cloud/web-search`
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

MVP provider support is Cloud-owned and configured only by Cloud operators:

- `MAGICK_CLOUD_WEB_SEARCH_PROVIDER`: `disabled`, `auto`, `tavily`, `bocha`, or
  `apify`
- `MAGICK_CLOUD_WEB_SEARCH_TAVILY_BASE_URL`: default `https://api.tavily.com`
- `MAGICK_CLOUD_WEB_SEARCH_TAVILY_API_KEY`: required when provider is `tavily`
  unless `MAGICK_CLOUD_WEB_SEARCH_TAVILY_API_KEYS` is configured
- `MAGICK_CLOUD_WEB_SEARCH_TAVILY_API_KEYS`: optional Cloud-operator key pool.
  Values may be comma-, semicolon-, whitespace-, or newline-separated. Cloud
  rotates keys in memory with round-robin selection and temporarily skips keys
  that return auth, rate-limit, timeout, network, or provider-unavailable
  failures. WordPress users never submit these keys through runtime requests.
- `MAGICK_CLOUD_WEB_SEARCH_TAVILY_TIMEOUT_SECONDS`: default `15`
- `MAGICK_CLOUD_WEB_SEARCH_TAVILY_COST_PER_QUERY`: optional shadow cost for
  provider-call usage records
- `MAGICK_CLOUD_WEB_SEARCH_BOCHA_BASE_URL`: default
  `https://api.bochaai.com/v1`
- `MAGICK_CLOUD_WEB_SEARCH_BOCHA_API_KEY`: required when provider is `bocha`
- `MAGICK_CLOUD_WEB_SEARCH_BOCHA_TIMEOUT_SECONDS`: default `15`
- `MAGICK_CLOUD_WEB_SEARCH_BOCHA_COST_PER_QUERY`: optional shadow cost
- `MAGICK_CLOUD_WEB_SEARCH_APIFY_BASE_URL`: default `https://api.apify.com/v2`
- `MAGICK_CLOUD_WEB_SEARCH_APIFY_API_TOKEN`: required when provider is `apify`
- `MAGICK_CLOUD_WEB_SEARCH_APIFY_ACTOR_ID`: default
  `apify/google-search-scraper`
- `MAGICK_CLOUD_WEB_SEARCH_APIFY_TIMEOUT_SECONDS`: default `30`
- `MAGICK_CLOUD_WEB_SEARCH_APIFY_COST_PER_QUERY`: optional shadow cost
- `MAGICK_CLOUD_WEB_SEARCH_JINA_READER_ENABLED`: enables selected URL reader
  enhancement after Tavily, Bocha, or Apify returns result URLs
- `MAGICK_CLOUD_WEB_SEARCH_JINA_READER_BASE_URL`: default `https://r.jina.ai`
- `MAGICK_CLOUD_WEB_SEARCH_JINA_READER_API_KEY`: optional/required depending on
  the Cloud operator's Jina Reader account policy
- `MAGICK_CLOUD_WEB_SEARCH_JINA_READER_MAX_PAGES`: default `2`, capped at `5`
- `MAGICK_CLOUD_WEB_SEARCH_ADMIN_ENV_PATH`: local operator settings file path
  for the Cloud admin provider settings page

The Cloud admin page `/admin/web-search` may update these runtime settings. It
must not expose plaintext secrets after save. Saving updates the current API
process settings and writes the configured env file; queue workers should be
restarted after provider changes so queued runs see the same configuration.

The WordPress-side search key path is intentionally removed from Toolbox. The
default customer path uses Cloud-managed search.

## Input Shape

```json
{
  "ability_name": "magick-ai-cloud/web-search",
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

## Site Knowledge Composition

Web Search is external-web evidence. Site Knowledge remains site-owned evidence
through `magick-ai-cloud/site-knowledge-search`. Product flows should combine
them explicitly:

- time-sensitive external facts: Web Search first
- site-specific assertions: Site Knowledge first
- article generation preflight: duplicate/refresh Site Knowledge plus external
  Web Search when current facts or sources are needed

If the evidence gate returns `insufficient_evidence`, AI callers must not state
time-sensitive or external facts as verified by web search.
