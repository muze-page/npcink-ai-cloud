from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from app.core.config import Settings
from app.domain.agent_workflow_metadata import (
    WEB_SEARCH_EVIDENCE_WORKFLOW_ID,
    get_workflow_metadata,
    registry_metadata_tokens,
)
from app.domain.web_search.contracts import (
    ALLOWED_WEB_SEARCH_INTENTS,
    SEARCH_EVIDENCE_PACK_CONTRACT,
    WEB_SEARCH_ABILITY,
    WEB_SEARCH_CONTRACT,
    WebSearchContractViolation,
    coerce_positive_int,
    validate_web_search_runtime_contract,
)

MAX_QUERY_CHARS = 500
MAX_RESULT_TITLE_CHARS = 220
MAX_RESULT_SNIPPET_CHARS = 600
MAX_DOMAIN_FILTERS = 10
WEB_SEARCH_PROVIDER_ORDER = ("tavily", "bocha", "apify")


@dataclass(slots=True)
class WebSearchProviderUsage:
    provider_id: str
    model_id: str
    instance_id: str
    region: str
    latency_ms: int
    cost: float = 0.0
    error_code: str | None = None


@dataclass(slots=True)
class WebSearchExecutionResult:
    result_json: dict[str, Any]
    usage: WebSearchProviderUsage


class WebSearchProviderError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        usage: WebSearchProviderUsage | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.usage = usage


class WebSearchService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def execute(
        self,
        *,
        site_id: str,
        ability_name: str,
        contract_version: str,
        input_payload: dict[str, Any],
        run_id: str,
    ) -> WebSearchExecutionResult:
        validate_web_search_runtime_contract(
            ability_name=ability_name,
            contract_version=contract_version,
            input_payload=input_payload,
        )
        query = _normalize_text(input_payload.get("query"), limit=MAX_QUERY_CHARS)
        if not query:
            raise WebSearchContractViolation(
                "web_search.query_required",
                "web search query is required",
            )
        options = _build_options(input_payload)
        options["ability_name"] = ability_name
        requested_provider = str(options.get("provider") or "").strip().lower()
        provider_id = (
            requested_provider
            or str(self.settings.web_search_provider or "disabled").strip().lower()
        )
        if provider_id == "disabled":
            raise WebSearchProviderError(
                "web_search.provider_not_configured",
                "Cloud-managed web search provider is not configured",
            )
        providers = (
            [provider_id]
            if provider_id != "auto"
            else [
                item
                for item in WEB_SEARCH_PROVIDER_ORDER
                if _provider_configured(self.settings, item)
            ]
        )
        if not providers:
            raise WebSearchProviderError(
                "web_search.provider_not_configured",
                "Cloud-managed web search provider is not configured",
            )

        errors: list[dict[str, str]] = []
        for candidate in providers:
            try:
                result = _build_provider(self.settings, candidate).search(
                    query=query,
                    options=options,
                    site_id=site_id,
                    run_id=run_id,
                )
            except WebSearchProviderError as error:
                if provider_id != "auto":
                    raise
                errors.append(
                    {
                        "provider": candidate,
                        "error_code": error.error_code,
                        "message": error.message,
                    }
                )
                continue
            if errors:
                result.result_json["provider_fallback_errors"] = errors
            result.result_json = _attach_web_search_workflow_metadata(
                result.result_json,
                options=options,
            )
            return _enhance_with_jina_reader(
                settings=self.settings,
                result=result,
                options=options,
            )

        raise WebSearchProviderError(
            "web_search.provider_fallback_exhausted",
            "Cloud-managed web search providers failed",
        )


class TavilyWebSearchProvider:
    provider_id = "tavily"
    model_id = "web-search"
    instance_id = "cloud-managed"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def search(
        self,
        *,
        query: str,
        options: dict[str, Any],
        site_id: str,
        run_id: str,
    ) -> WebSearchExecutionResult:
        api_key = str(self.settings.web_search_tavily_api_key or "").strip()
        if not api_key:
            raise WebSearchProviderError(
                "web_search.tavily_api_key_missing",
                "Cloud-managed Tavily API key is not configured",
            )
        base_url = str(self.settings.web_search_tavily_base_url or "").strip().rstrip("/")
        endpoint = f"{base_url}/search"
        max_results = coerce_positive_int(options.get("max_results"), default=5, maximum=10)
        request_body: dict[str, Any] = {
            "api_key": api_key,
            "query": query,
            "search_depth": str(options.get("search_depth") or "basic"),
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
        }
        if int(options.get("recency_days") or 0) > 0:
            request_body["days"] = int(options.get("recency_days") or 0)
        if options.get("language"):
            request_body["language"] = str(options["language"])
        if options.get("region"):
            request_body["region"] = str(options["region"])
        if options.get("allowed_domains"):
            request_body["include_domains"] = list(options["allowed_domains"])
        if options.get("blocked_domains"):
            request_body["exclude_domains"] = list(options["blocked_domains"])

        started = time.monotonic()
        try:
            timeout_seconds = float(self.settings.web_search_tavily_timeout_seconds)
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.post(endpoint, json=request_body)
                response.raise_for_status()
        except httpx.TimeoutException as error:
            usage = self._usage(started, error_code="provider.timeout")
            raise WebSearchProviderError(
                "provider.timeout",
                "Tavily web search timed out",
                usage=usage,
            ) from error
        except httpx.HTTPStatusError as error:
            usage = self._usage(started, error_code=_map_tavily_error(error.response))
            raise WebSearchProviderError(
                usage.error_code or "web_search.tavily_http_error",
                _extract_http_error_message(error.response),
                usage=usage,
            ) from error
        except httpx.RequestError as error:
            usage = self._usage(started, error_code="provider.network_error")
            raise WebSearchProviderError(
                "provider.network_error",
                "Tavily web search request failed",
                usage=usage,
            ) from error

        usage = self._usage(started)
        try:
            payload = response.json()
        except ValueError as error:
            usage.error_code = "provider.invalid_response"
            raise WebSearchProviderError(
                "provider.invalid_response",
                "Tavily web search returned invalid JSON",
                usage=usage,
            ) from error
        raw_results = payload.get("results") if isinstance(payload, dict) else []
        if not isinstance(raw_results, list):
            raw_results = []
        intent = str(options.get("intent") or "general_research")
        results = _normalize_results(raw_results, intent=intent, provider_id=self.provider_id)
        evidence_policy = _resolve_evidence_policy(options.get("evidence_policy"))
        results = _apply_evidence_policy(results, evidence_policy)
        result_json = _build_result_json(
            provider_id=self.provider_id,
            query=query,
            options=options,
            results=results,
            evidence_policy=evidence_policy,
        )
        return WebSearchExecutionResult(result_json=result_json, usage=usage)

    def _usage(self, started: float, *, error_code: str | None = None) -> WebSearchProviderUsage:
        return WebSearchProviderUsage(
            provider_id=self.provider_id,
            model_id=self.model_id,
            instance_id=self.instance_id,
            region=str(self.settings.deployment_region or "unspecified"),
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
            cost=max(0.0, float(self.settings.web_search_tavily_cost_per_query or 0.0)),
            error_code=error_code,
        )


class BochaWebSearchProvider:
    provider_id = "bocha"
    model_id = "web-search"
    instance_id = "cloud-managed"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def search(
        self,
        *,
        query: str,
        options: dict[str, Any],
        site_id: str,
        run_id: str,
    ) -> WebSearchExecutionResult:
        api_key = str(self.settings.web_search_bocha_api_key or "").strip()
        if not api_key:
            raise WebSearchProviderError(
                "web_search.bocha_api_key_missing",
                "Cloud-managed Bocha API key is not configured",
            )
        base_url = str(self.settings.web_search_bocha_base_url or "").strip().rstrip("/")
        endpoint = f"{base_url}/web-search"
        max_results = coerce_positive_int(options.get("max_results"), default=5, maximum=10)
        request_body: dict[str, Any] = {
            "query": query,
            "count": max_results,
            "summary": True,
        }
        if int(options.get("recency_days") or 0) > 0:
            request_body["freshness"] = f"{int(options['recency_days'])}d"

        started = time.monotonic()
        try:
            with httpx.Client(
                timeout=float(self.settings.web_search_bocha_timeout_seconds)
            ) as client:
                response = client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=request_body,
                )
                response.raise_for_status()
        except httpx.TimeoutException as error:
            usage = self._usage(started, error_code="provider.timeout")
            raise WebSearchProviderError(
                "provider.timeout",
                "Bocha web search timed out",
                usage=usage,
            ) from error
        except httpx.HTTPStatusError as error:
            usage = self._usage(started, error_code=_map_provider_http_error(error.response))
            raise WebSearchProviderError(
                usage.error_code or "web_search.bocha_http_error",
                _extract_http_error_message(error.response),
                usage=usage,
            ) from error
        except httpx.RequestError as error:
            usage = self._usage(started, error_code="provider.network_error")
            raise WebSearchProviderError(
                "provider.network_error",
                "Bocha web search request failed",
                usage=usage,
            ) from error

        usage = self._usage(started)
        payload = _json_payload(response, provider_id=self.provider_id, usage=usage)
        raw_results = payload.get("webPages", {}).get("value") if isinstance(payload, dict) else []
        if not isinstance(raw_results, list):
            raw_results = []
        intent = str(options.get("intent") or "general_research")
        results = _normalize_results(
            raw_results,
            intent=intent,
            provider_id=self.provider_id,
            title_keys=("name", "title"),
            url_keys=("url",),
            snippet_keys=("snippet", "summary", "content"),
        )
        evidence_policy = _resolve_evidence_policy(options.get("evidence_policy"))
        results = _apply_evidence_policy(results, evidence_policy)
        return WebSearchExecutionResult(
            result_json=_build_result_json(
                provider_id=self.provider_id,
                query=query,
                options=options,
                results=results,
                evidence_policy=evidence_policy,
            ),
            usage=usage,
        )

    def _usage(self, started: float, *, error_code: str | None = None) -> WebSearchProviderUsage:
        return WebSearchProviderUsage(
            provider_id=self.provider_id,
            model_id=self.model_id,
            instance_id=self.instance_id,
            region=str(self.settings.deployment_region or "unspecified"),
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
            cost=max(0.0, float(self.settings.web_search_bocha_cost_per_query or 0.0)),
            error_code=error_code,
        )


class ApifyWebSearchProvider:
    provider_id = "apify"
    model_id = "web-search"
    instance_id = "cloud-managed"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def search(
        self,
        *,
        query: str,
        options: dict[str, Any],
        site_id: str,
        run_id: str,
    ) -> WebSearchExecutionResult:
        api_token = str(self.settings.web_search_apify_api_token or "").strip()
        actor_id = str(self.settings.web_search_apify_actor_id or "").strip()
        if not api_token:
            raise WebSearchProviderError(
                "web_search.apify_api_token_missing",
                "Cloud-managed Apify API token is not configured",
            )
        if not actor_id:
            raise WebSearchProviderError(
                "web_search.apify_actor_missing",
                "Cloud-managed Apify actor is not configured",
            )
        base_url = str(self.settings.web_search_apify_base_url or "").strip().rstrip("/")
        endpoint = f"{base_url}/acts/{quote(actor_id, safe='')}/run-sync-get-dataset-items"
        max_results = coerce_positive_int(options.get("max_results"), default=5, maximum=10)
        request_body = {
            "queries": query,
            "maxResults": max_results,
            "resultsPerPage": max_results,
            "maxPagesPerQuery": 1,
            "language": str(options.get("language") or ""),
            "countryCode": str(options.get("region") or ""),
        }
        started = time.monotonic()
        try:
            with httpx.Client(
                timeout=float(self.settings.web_search_apify_timeout_seconds)
            ) as client:
                response = client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {api_token}"},
                    json=request_body,
                )
                response.raise_for_status()
        except httpx.TimeoutException as error:
            usage = self._usage(started, error_code="provider.timeout")
            raise WebSearchProviderError(
                "provider.timeout",
                "Apify web search timed out",
                usage=usage,
            ) from error
        except httpx.HTTPStatusError as error:
            usage = self._usage(started, error_code=_map_provider_http_error(error.response))
            raise WebSearchProviderError(
                usage.error_code or "web_search.apify_http_error",
                _extract_http_error_message(error.response),
                usage=usage,
            ) from error
        except httpx.RequestError as error:
            usage = self._usage(started, error_code="provider.network_error")
            raise WebSearchProviderError(
                "provider.network_error",
                "Apify web search request failed",
                usage=usage,
            ) from error

        usage = self._usage(started)
        payload = _json_payload(response, provider_id=self.provider_id, usage=usage)
        raw_results = payload if isinstance(payload, list) else payload.get("items", [])
        if not isinstance(raw_results, list):
            raw_results = []
        raw_results = _flatten_apify_search_results(raw_results, max_results=max_results)
        intent = str(options.get("intent") or "general_research")
        results = _normalize_results(
            raw_results,
            intent=intent,
            provider_id=self.provider_id,
            title_keys=("title", "name"),
            url_keys=("url", "link"),
            snippet_keys=("description", "snippet", "text", "content"),
        )
        evidence_policy = _resolve_evidence_policy(options.get("evidence_policy"))
        results = _apply_evidence_policy(results, evidence_policy)
        return WebSearchExecutionResult(
            result_json=_build_result_json(
                provider_id=self.provider_id,
                query=query,
                options=options,
                results=results,
                evidence_policy=evidence_policy,
            ),
            usage=usage,
        )

    def _usage(self, started: float, *, error_code: str | None = None) -> WebSearchProviderUsage:
        return WebSearchProviderUsage(
            provider_id=self.provider_id,
            model_id=self.model_id,
            instance_id=self.instance_id,
            region=str(self.settings.deployment_region or "unspecified"),
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
            cost=max(0.0, float(self.settings.web_search_apify_cost_per_query or 0.0)),
            error_code=error_code,
        )


def _flatten_apify_search_results(
    raw_results: list[Any],
    *,
    max_results: int,
) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        organic_results = item.get("organicResults")
        if isinstance(organic_results, list):
            for organic_result in organic_results:
                if isinstance(organic_result, dict):
                    flattened.append(organic_result)
                if len(flattened) >= max_results:
                    return flattened
            continue
        flattened.append(item)
        if len(flattened) >= max_results:
            return flattened
    return flattened


def _build_options(input_payload: dict[str, Any]) -> dict[str, Any]:
    intent = str(input_payload.get("intent") or "general_research").strip()
    if intent not in ALLOWED_WEB_SEARCH_INTENTS:
        intent = "general_research"
    provider = str(input_payload.get("provider") or "").strip().lower()
    if provider not in {"", "auto", *WEB_SEARCH_PROVIDER_ORDER}:
        provider = ""
    return {
        "intent": intent,
        "provider": provider,
        "max_results": coerce_positive_int(input_payload.get("max_results"), default=5, maximum=10),
        "recency_days": max(0, min(30, _coerce_int(input_payload.get("recency_days")))),
        "language": _normalize_token(input_payload.get("language"), limit=16),
        "region": _normalize_token(input_payload.get("region"), limit=16),
        "search_depth": _normalize_search_depth(input_payload.get("search_depth")),
        "allowed_domains": _normalize_domain_list(input_payload.get("allowed_domains")),
        "blocked_domains": _normalize_domain_list(input_payload.get("blocked_domains")),
        "enhance_with_reader": bool(input_payload.get("enhance_with_reader")),
        "evidence_policy": input_payload.get("evidence_policy"),
    }


def _build_provider(
    settings: Settings,
    provider_id: str,
) -> TavilyWebSearchProvider | BochaWebSearchProvider | ApifyWebSearchProvider:
    if provider_id == "tavily":
        return TavilyWebSearchProvider(settings)
    if provider_id == "bocha":
        return BochaWebSearchProvider(settings)
    if provider_id == "apify":
        return ApifyWebSearchProvider(settings)
    raise WebSearchProviderError(
        "web_search.provider_not_supported",
        "Cloud-managed web search provider is not supported",
    )


def _provider_configured(settings: Settings, provider_id: str) -> bool:
    if provider_id == "tavily":
        return bool(str(settings.web_search_tavily_api_key or "").strip())
    if provider_id == "bocha":
        return bool(str(settings.web_search_bocha_api_key or "").strip())
    if provider_id == "apify":
        return bool(
            str(settings.web_search_apify_api_token or "").strip()
            and str(settings.web_search_apify_actor_id or "").strip()
        )
    return False


def _build_result_json(
    *,
    provider_id: str,
    query: str,
    options: dict[str, Any],
    results: list[dict[str, Any]],
    evidence_policy: dict[str, Any],
) -> dict[str, Any]:
    evidence_gate = _evidence_gate(results, evidence_policy)
    evidence_pack = _build_search_evidence_pack(
        provider_id=provider_id,
        query=query,
        options=options,
        results=results,
        evidence_policy=evidence_policy,
        evidence_gate=evidence_gate,
    )
    return {
        "artifact_type": "web_search_results",
        "composition_role": "external_web_evidence",
        "status": "ready",
        "provider": provider_id,
        "intent": str(options.get("intent") or "general_research"),
        "query_hash": _hash_query(query),
        "query_chars": len(query),
        "output_contract": SEARCH_EVIDENCE_PACK_CONTRACT,
        "evidence_gate": evidence_gate,
        "evidence_pack": evidence_pack,
        "workflow_metadata": _web_search_workflow_metadata(options),
        "results": results,
        "sources": [
            {
                "title": str(item.get("title") or ""),
                "url": str(item.get("url") or ""),
                "source": provider_id,
            }
            for item in results
        ],
        "write_posture": "suggestion_only",
        "direct_wordpress_write": False,
    }


def _attach_web_search_workflow_metadata(
    result_json: dict[str, Any],
    *,
    options: dict[str, Any],
) -> dict[str, Any]:
    updated = dict(result_json)
    updated["workflow_metadata"] = _web_search_workflow_metadata(options)
    return updated


def _web_search_workflow_metadata(options: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(get_workflow_metadata(WEB_SEARCH_EVIDENCE_WORKFLOW_ID))
    metadata.update(
        {
            "workflow_kind": "fixed_evidence_workflow",
            "triggering_ability": str(options.get("ability_name") or WEB_SEARCH_ABILITY),
            "triggering_contract": WEB_SEARCH_CONTRACT,
            "intent": str(options.get("intent") or "general_research"),
            "cloud_output": "external_web_evidence",
            "output_contract": SEARCH_EVIDENCE_PACK_CONTRACT,
            "write_posture": "suggestion_only",
            "steps": registry_metadata_tokens(metadata.get("steps")),
            "stop_conditions": registry_metadata_tokens(metadata.get("stop_conditions")),
        }
    )
    return metadata


def _enhance_with_jina_reader(
    *,
    settings: Settings,
    result: WebSearchExecutionResult,
    options: dict[str, Any],
) -> WebSearchExecutionResult:
    if not (
        bool(settings.web_search_jina_reader_enabled) or bool(options.get("enhance_with_reader"))
    ):
        return result
    base_url = str(settings.web_search_jina_reader_base_url or "").strip().rstrip("/")
    if not base_url:
        return result
    max_pages = max(1, min(5, int(settings.web_search_jina_reader_max_pages or 1)))
    headers = {"Accept": "text/plain"}
    api_key = str(settings.web_search_jina_reader_api_key or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    enhanced = 0
    errors: list[dict[str, str]] = []
    started = time.monotonic()
    with httpx.Client(timeout=float(settings.web_search_jina_reader_timeout_seconds)) as client:
        for item in result.result_json.get("results", [])[:max_pages]:
            if not isinstance(item, dict):
                continue
            url = _normalize_url(item.get("url"))
            if not url:
                continue
            try:
                response = client.get(f"{base_url}/{url}", headers=headers)
                response.raise_for_status()
            except (httpx.TimeoutException, httpx.HTTPError) as error:
                errors.append(
                    {
                        "url_hash": _hash_query(url),
                        "error_code": "provider.reader_error",
                        "message": str(error)[:160],
                    }
                )
                continue
            excerpt = _normalize_text(response.text, limit=1200)
            if not excerpt:
                continue
            item["reader_status"] = "ready"
            item["reader_excerpt"] = excerpt
            item["reader_provider"] = "jina_reader"
            enhanced += 1

    result.result_json["reader_enhancement"] = {
        "provider": "jina_reader",
        "status": "ready" if enhanced else "no_enhancement",
        "enhanced_count": enhanced,
        "error_count": len(errors),
        "errors": errors[:5],
    }
    result.usage.cost += (
        max(0.0, float(settings.web_search_jina_reader_cost_per_page or 0.0)) * enhanced
    )
    result.usage.latency_ms += max(0, int((time.monotonic() - started) * 1000))
    return result


def _json_payload(
    response: httpx.Response,
    *,
    provider_id: str,
    usage: WebSearchProviderUsage,
) -> Any:
    try:
        return response.json()
    except ValueError as error:
        usage.error_code = "provider.invalid_response"
        raise WebSearchProviderError(
            "provider.invalid_response",
            f"{provider_id} web search returned invalid JSON",
            usage=usage,
        ) from error


def _normalize_results(
    raw_results: list[Any],
    *,
    intent: str,
    provider_id: str,
    title_keys: tuple[str, ...] = ("title",),
    url_keys: tuple[str, ...] = ("url",),
    snippet_keys: tuple[str, ...] = ("content", "snippet"),
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in raw_results:
        if not isinstance(raw, dict):
            continue
        title = _normalize_text(_first_value(raw, title_keys), limit=MAX_RESULT_TITLE_CHARS)
        url = _normalize_url(_first_value(raw, url_keys))
        snippet = _normalize_text(
            _first_value(raw, snippet_keys),
            limit=MAX_RESULT_SNIPPET_CHARS,
        )
        if not url and not title and not snippet:
            continue
        normalized.append(
            {
                "title": title or "Untitled result",
                "url": url,
                "snippet": snippet,
                "score": _coerce_score(raw.get("score")),
                "source": provider_id,
                "suggested_use": _suggested_use(intent),
                "write_posture": "suggestion_only",
                "direct_wordpress_write": False,
            }
        )
    return normalized


def _resolve_evidence_policy(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    min_score = _coerce_float(raw.get("min_score"), default=0.0)
    required_sources = coerce_positive_int(raw.get("required_sources"), default=1, maximum=5)
    no_hit_policy = str(raw.get("no_hit_policy") or "abstain").strip()
    if no_hit_policy not in {"abstain", "fallback_to_general"}:
        no_hit_policy = "abstain"
    return {
        "min_score": max(0.0, min(1.0, min_score)),
        "required_sources": required_sources,
        "no_hit_policy": no_hit_policy,
    }


def _apply_evidence_policy(
    results: list[dict[str, Any]],
    evidence_policy: dict[str, Any],
) -> list[dict[str, Any]]:
    min_score = float(evidence_policy.get("min_score") or 0.0)
    return [item for item in results if float(item.get("score") or 0.0) >= min_score]


def _evidence_gate(
    results: list[dict[str, Any]],
    evidence_policy: dict[str, Any],
) -> dict[str, Any]:
    source_count = len([item for item in results if str(item.get("url") or "")])
    required_sources = int(evidence_policy.get("required_sources") or 1)
    passed = source_count >= required_sources
    return {
        "status": "passed" if passed else "insufficient_evidence",
        "min_score": float(evidence_policy.get("min_score") or 0.0),
        "required_sources": required_sources,
        "source_count": source_count,
        "no_hit_policy": str(evidence_policy.get("no_hit_policy") or "abstain"),
        "allows_web_grounded_assertion": passed,
        "guidance": (
            "Use returned web sources as external grounding evidence."
            if passed
            else "Do not state time-sensitive or external facts as verified from web search."
        ),
    }


def _suggested_use(intent: str) -> str:
    return {
        "article_background": "article_background_source",
        "fact_check": "verify_external_fact",
        "news": "time_sensitive_context",
        "writing_context": "external_writing_context",
        "competitor_research": "competitor_context",
        "pricing_snapshot": "pricing_context",
        "product_comparison": "product_comparison_context",
        "source_discovery": "source_candidate",
        "external_links": "external_link_candidate",
    }.get(intent, "external_research")


def _build_search_evidence_pack(
    *,
    provider_id: str,
    query: str,
    options: dict[str, Any],
    results: list[dict[str, Any]],
    evidence_policy: dict[str, Any],
    evidence_gate: dict[str, Any],
) -> dict[str, Any]:
    intent = str(options.get("intent") or "general_research")
    source_cards = [_source_card(item, provider_id=provider_id) for item in results]
    source_count = len([item for item in source_cards if str(item.get("url") or "")])
    return {
        "artifact_type": "search_evidence_pack",
        "contract_version": SEARCH_EVIDENCE_PACK_CONTRACT,
        "pack_type": _evidence_pack_type(intent),
        "intent": intent,
        "status": str(evidence_gate.get("status") or "insufficient_evidence"),
        "query_hash": _hash_query(query),
        "result_count": len(results),
        "source_count": source_count,
        "required_sources": int(evidence_policy.get("required_sources") or 1),
        "provider": provider_id,
        "sections": _evidence_pack_sections(intent),
        "source_cards": source_cards,
        "citation_candidates": source_cards,
        "guidance": _evidence_pack_guidance(intent, evidence_gate),
        "write_posture": "suggestion_only",
        "direct_wordpress_write": False,
    }


def _source_card(item: dict[str, Any], *, provider_id: str) -> dict[str, Any]:
    return {
        "title": _normalize_text(item.get("title"), limit=MAX_RESULT_TITLE_CHARS),
        "url": _normalize_url(item.get("url")),
        "snippet": _normalize_text(item.get("snippet"), limit=MAX_RESULT_SNIPPET_CHARS),
        "source": str(item.get("source") or provider_id),
        "suggested_use": str(item.get("suggested_use") or ""),
        "citation_candidate": bool(item.get("url")),
        "write_posture": "suggestion_only",
        "direct_wordpress_write": False,
    }


def _evidence_pack_type(intent: str) -> str:
    return {
        "article_background": "article_background",
        "fact_check": "fact_check",
        "competitor_research": "competitor_snapshot",
        "pricing_snapshot": "pricing_snapshot",
        "product_comparison": "product_comparison",
    }.get(intent, "external_research")


def _evidence_pack_sections(intent: str) -> list[str]:
    return {
        "article_background": [
            "current_background",
            "citation_candidates",
            "risk_notes",
        ],
        "fact_check": [
            "claims_to_verify",
            "supporting_sources",
            "manual_review_notes",
        ],
        "competitor_research": [
            "competitor_sources",
            "positioning_signals",
            "comparison_notes",
        ],
        "pricing_snapshot": [
            "pricing_sources",
            "plan_or_offer_signals",
            "freshness_notes",
        ],
        "product_comparison": [
            "product_sources",
            "feature_signals",
            "comparison_notes",
        ],
    }.get(intent, ["external_sources", "citation_candidates", "risk_notes"])


def _evidence_pack_guidance(intent: str, evidence_gate: dict[str, Any]) -> str:
    if str(evidence_gate.get("status") or "") != "passed":
        return "Treat this pack as insufficient evidence and ask for manual review before making current factual claims."
    return {
        "article_background": "Use as a pre-writing background pack. Cite sources for current claims and keep final writes local-governed.",
        "fact_check": "Use as supporting evidence for claim review. Do not mark unsupported claims as verified.",
        "competitor_research": "Use as a lightweight competitor snapshot, not a durable competitor database.",
        "pricing_snapshot": "Use as a point-in-time pricing snapshot. Re-check before publishing pricing claims.",
        "product_comparison": "Use as a lightweight comparison input. Confirm important claims manually before publishing.",
    }.get(
        intent,
        "Use returned web sources as external grounding evidence. Keep conclusions suggestion-only.",
    )


def _normalize_domain_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    domains: list[str] = []
    seen: set[str] = set()
    for item in value:
        domain = str(item or "").strip().lower()
        if "://" in domain:
            parsed = urlsplit(domain)
            domain = parsed.netloc.lower()
        domain = domain.strip("/")
        if not domain or "/" in domain or domain in seen:
            continue
        seen.add(domain)
        domains.append(domain)
        if len(domains) >= MAX_DOMAIN_FILTERS:
            break
    return domains


def _normalize_search_depth(value: Any) -> str:
    depth = str(value or "basic").strip().lower()
    return depth if depth in {"basic", "advanced"} else "basic"


def _normalize_text(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


def _normalize_token(value: Any, *, limit: int) -> str:
    return _normalize_text(value, limit=limit).replace(" ", "")


def _first_value(raw: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = raw.get(key)
        if value:
            return value
    return ""


def _normalize_url(value: Any) -> str:
    url = str(value or "").strip()
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return url


def _coerce_score(value: Any) -> float:
    return max(0.0, min(1.0, _coerce_float(value, default=1.0)))


def _coerce_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _hash_query(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def _map_tavily_error(response: httpx.Response) -> str:
    return _map_provider_http_error(response)


def _map_provider_http_error(response: httpx.Response) -> str:
    if response.status_code in {401, 403}:
        return "provider.auth_invalid"
    if response.status_code == 429:
        return "provider.rate_limited"
    if response.status_code >= 500:
        return "provider.unavailable"
    return "web_search.tavily_http_error"


def _extract_http_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if isinstance(payload, dict):
        message = str(payload.get("message") or payload.get("error") or "").strip()
        if message:
            return message[:200]
    return f"Tavily web search failed with HTTP {response.status_code}"
