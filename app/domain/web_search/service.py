from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, TypedDict
from urllib.parse import quote, urlsplit

import httpx

from app.core.config import Settings
from app.domain.agent_workflow_metadata import (
    WEB_SEARCH_EVIDENCE_WORKFLOW_ID,
    get_workflow_metadata,
    metadata_projection_tokens,
)
from app.domain.web_search.contracts import (
    ALLOWED_WEB_SEARCH_INTENTS,
    ATOMIC_OUTPUT_CONTRACTS,
    GROUNDED_ANSWER_CONTRACT,
    SEARCH_EVIDENCE_PACK_CONTRACT,
    SOURCE_EVIDENCE_CONTRACT,
    SOURCE_EXTRACTION_PREVIEW_CONTRACT,
    TOPIC_CANDIDATE_CONTRACT,
    WEB_SEARCH_ABILITY,
    WEB_SEARCH_CONTRACT,
    WebSearchContractViolation,
    coerce_positive_int,
    validate_public_source_url,
    validate_web_search_runtime_contract,
)

MAX_QUERY_CHARS = 500
MAX_RESULT_TITLE_CHARS = 220
MAX_RESULT_SNIPPET_CHARS = 600
MAX_DOMAIN_FILTERS = 10
MAX_PROVIDER_RESPONSE_BYTES = 2_000_000
MAX_READER_RESPONSE_BYTES = 500_000
MAX_SOURCE_READER_CONTENT_CHARS = 8_000
MAX_SOURCE_PREVIEW_CHARS = 600
WEB_SEARCH_PROVIDER_ORDER = ("tavily", "bocha", "apify", "zhihu")
TAVILY_KEY_QUARANTINE_SECONDS = 300.0
_TAVILY_POOL_LOCK = threading.Lock()
_TAVILY_POOL_CURSOR: dict[str, int] = {}
_TAVILY_POOL_QUARANTINED_UNTIL: dict[tuple[str, str], float] = {}
_ZHIHU_HOT_LIST_LOCK = threading.Lock()
_ZHIHU_HOT_LIST_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
ZHIHU_PLAYGROUND_INVOKE_PATH = "/api/v1/playground/invoke"
ZHIHU_SEARCH_API_ID = "zhihu_search"
ZHIHU_GLOBAL_SEARCH_API_ID = "global_search"
ZHIHU_HOT_LIST_API_ID = "hot_list"
ZHIHU_DIRECT_ANSWER_API_ID = "zhida_openai"
ZHIHU_DIRECT_ANSWER_SOURCE_TYPES = frozenset(
    {"zhida_simple", "zhida_deep", "zhida_deepsearch"}
)
ZHIHU_DIRECT_ANSWER_MODES = {
    "zhida_simple": "simple",
    "zhida_deep": "deep",
    "zhida_deepsearch": "deepsearch",
}
ZHIHU_DIRECT_ANSWER_MODELS = {
    "zhida_simple": "zhida-fast-1p5",
    "zhida_deep": "zhida-thinking-1p5",
    "zhida_deepsearch": "zhida-agent",
}


class _TavilyApiKeySelection(TypedDict):
    api_key: str
    index: int
    key_count: int
    fingerprint: str
    pool_id: str
    label: str


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
        if str(options.get("intent") or "") == "source_extraction_preview":
            source_url = validate_public_source_url(
                input_payload.get("source_url") or input_payload.get("query")
            )
            return _extract_source_preview(
                settings=self.settings,
                source_url=source_url,
                options=options,
            )
        requested_provider = str(options.get("provider") or "").strip().lower()
        provider_id = (
            requested_provider
            or str(self.settings.web_search_provider or "disabled").strip().lower()
        )
        options["provider_mode"] = provider_id
        options["requested_provider"] = requested_provider
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
            result.result_json["provider_mode"] = str(
                result.result_json.get("provider_mode") or provider_id
            )
            result.result_json["requested_provider"] = str(
                result.result_json.get("requested_provider") or requested_provider
            )
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
        api_keys = _tavily_api_key_pool(self.settings)
        if not api_keys:
            raise WebSearchProviderError(
                "web_search.tavily_api_key_missing",
                "Cloud-managed Tavily API key is not configured",
            )
        base_url = str(self.settings.web_search_tavily_base_url or "").strip().rstrip("/")
        endpoint = f"{base_url}/search"
        max_results = coerce_positive_int(options.get("max_results"), default=5, maximum=10)
        started = time.monotonic()
        key_errors: list[dict[str, object]] = []
        selection: _TavilyApiKeySelection | None = None
        response: httpx.Response | None = None
        last_error: Exception | None = None
        last_error_code: str | None = None
        last_error_message = "Tavily web search request failed"

        for _attempt in range(len(api_keys)):
            selection = _select_tavily_api_key(
                api_keys,
                labels=_tavily_api_key_labels(self.settings, len(api_keys)),
            )
            external_query = _provider_query(
                query,
                str(options.get("intent") or "general_research"),
            )
            request_body: dict[str, Any] = {
                "api_key": str(selection["api_key"]),
                "query": external_query,
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

            try:
                timeout_seconds = float(self.settings.web_search_tavily_timeout_seconds)
                with httpx.Client(timeout=timeout_seconds) as client:
                    response = client.post(endpoint, json=request_body)
                    response.raise_for_status()
                break
            except httpx.TimeoutException as error:
                last_error = error
                last_error_code = "provider.timeout"
                last_error_message = "Tavily web search timed out"
            except httpx.HTTPStatusError as error:
                last_error = error
                last_error_code = _map_tavily_error(error.response)
                last_error_message = _extract_http_error_message(
                    error.response,
                    provider_id=self.provider_id,
                )
            except httpx.RequestError as error:
                last_error = error
                last_error_code = "provider.network_error"
                last_error_message = "Tavily web search request failed"

            key_errors.append(
                {
                    "error_code": last_error_code or "provider.error",
                    "selected_key_index": int(selection["index"]) + 1,
                }
            )
            if not _should_quarantine_tavily_key(last_error_code):
                break
            _quarantine_tavily_api_key(
                pool_id=str(selection["pool_id"]),
                fingerprint=str(selection["fingerprint"]),
            )

        if response is None:
            usage = self._usage(started, error_code=last_error_code)
            raise WebSearchProviderError(
                last_error_code or "web_search.tavily_http_error",
                last_error_message,
                usage=usage,
            ) from last_error

        usage = self._usage(started)
        try:
            payload = _json_payload(response, provider_id=self.provider_id, usage=usage)
        except WebSearchProviderError:
            raise
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
        if selection and int(selection["key_count"]) > 1:
            result_json["provider_key_pool"] = {
                "provider": "tavily",
                "strategy": "round_robin_with_temporary_quarantine",
                "key_count": int(selection["key_count"]),
                "selected_key_index": int(selection["index"]) + 1,
                "attempt_count": len(key_errors) + 1,
                "failover_count": len(key_errors),
                "errors": key_errors[:5],
            }
            if str(selection.get("label") or "").strip():
                result_json["provider_key_pool"]["selected_key_label"] = str(selection["label"])
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
        external_query = _provider_query(
            query,
            str(options.get("intent") or "general_research"),
        )
        request_body: dict[str, Any] = {
            "query": external_query,
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
                _extract_http_error_message(error.response, provider_id=self.provider_id),
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
        external_query = _provider_query(
            query,
            str(options.get("intent") or "general_research"),
        )
        request_body = {
            "queries": external_query,
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
                _extract_http_error_message(error.response, provider_id=self.provider_id),
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


class ZhihuWebSearchProvider:
    provider_id = "zhihu"
    model_id = "zhihu-openapi-content"
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
        access_secret = str(self.settings.web_search_zhihu_access_secret or "").strip()
        if not access_secret:
            raise WebSearchProviderError(
                "web_search.zhihu_access_secret_missing",
                "Cloud-managed Zhihu access secret is not configured",
            )
        base_url = str(self.settings.web_search_zhihu_base_url or "").strip().rstrip("/")
        max_results = coerce_positive_int(options.get("max_results"), default=5, maximum=10)
        source_type = str(options.get("source_type") or "zhihu_search")
        include_hot_list = bool(options.get("include_hot_list"))
        started = time.monotonic()
        try:
            with httpx.Client(
                timeout=float(self.settings.web_search_zhihu_timeout_seconds)
            ) as client:
                raw_results: list[dict[str, Any]] = []
                if source_type == "zhihu_hot_list":
                    raw_results.extend(
                        self._hot_list_items(
                            client,
                            base_url=base_url,
                            access_secret=access_secret,
                            limit=min(30, max(5, max_results)),
                        )
                    )
                elif source_type == "zhihu_global_search":
                    endpoint = self._endpoint(
                        base_url,
                        str(self.settings.web_search_zhihu_global_search_path or ""),
                        setting_name="web_search_zhihu_global_search_path",
                    )
                    if _is_zhihu_playground_endpoint(endpoint):
                        payload: dict[str, Any] = {"Query": query, "Count": max_results}
                        date_filter = _zhihu_global_filter(options.get("recency_days"))
                        if date_filter:
                            payload["Filter"] = date_filter
                        global_payload = self._post_playground_json(
                            client,
                            endpoint,
                            access_secret=access_secret,
                            api_id=ZHIHU_GLOBAL_SEARCH_API_ID,
                            payload=payload,
                        )
                    else:
                        global_payload = self._get_json(
                            client,
                            endpoint,
                            access_secret=access_secret,
                            params={"Query": query, "Count": str(max_results)},
                        )
                    raw_results = [
                        {**item, "source": "zhihu_global_search"}
                        for item in _zhihu_items(global_payload)
                    ]
                elif source_type in ZHIHU_DIRECT_ANSWER_SOURCE_TYPES:
                    endpoint = self._endpoint(
                        base_url,
                        str(self.settings.web_search_zhihu_direct_answer_path or ""),
                        setting_name="web_search_zhihu_direct_answer_path",
                    )
                    usage = self._usage(started)
                    intent = str(options.get("intent") or source_type)
                    try:
                        if _is_zhihu_playground_endpoint(endpoint):
                            answer = self._post_playground_direct_answer(
                                client,
                                endpoint,
                                access_secret=access_secret,
                                query=query,
                                source_type=source_type,
                            )
                        elif _is_zhihu_chat_completions_endpoint(endpoint):
                            answer = self._post_zhida_chat_completion(
                                client,
                                endpoint,
                                access_secret=access_secret,
                                query=query,
                                source_type=source_type,
                            )
                        else:
                            answer_payload = self._get_json(
                                client,
                                endpoint,
                                access_secret=access_secret,
                                params={
                                    "Query": query,
                                    "Mode": ZHIHU_DIRECT_ANSWER_MODES[source_type],
                                    "Count": str(max_results),
                                },
                            )
                            answer = _zhihu_direct_answer(answer_payload)
                    except httpx.TimeoutException:
                        usage = self._usage(started, error_code="provider.timeout")
                        return WebSearchExecutionResult(
                            result_json=_build_direct_answer_degraded_result_json(
                                provider_id=self.provider_id,
                                query=query,
                                options=options,
                                intent=intent,
                                mode=ZHIHU_DIRECT_ANSWER_MODES[source_type],
                                error_code="provider.timeout",
                                error_message="Zhihu OpenAPI request timed out",
                            ),
                            usage=usage,
                        )
                    except httpx.HTTPStatusError as error:
                        error_code = _map_provider_http_error(error.response)
                        if error_code not in {
                            "provider.rate_limited",
                            "provider.unavailable",
                        }:
                            raise
                        usage = self._usage(started, error_code=error_code)
                        return WebSearchExecutionResult(
                            result_json=_build_direct_answer_degraded_result_json(
                                provider_id=self.provider_id,
                                query=query,
                                options=options,
                                intent=intent,
                                mode=ZHIHU_DIRECT_ANSWER_MODES[source_type],
                                error_code=error_code,
                                error_message=_extract_http_error_message(
                                    error.response,
                                    provider_id=self.provider_id,
                                ),
                            ),
                            usage=usage,
                        )
                    return WebSearchExecutionResult(
                        result_json=_build_direct_answer_result_json(
                            provider_id=self.provider_id,
                            query=query,
                            options=options,
                            answer=answer,
                            intent=intent,
                            mode=ZHIHU_DIRECT_ANSWER_MODES[source_type],
                        ),
                        usage=usage,
                    )
                else:
                    endpoint = self._endpoint(
                        base_url,
                        str(self.settings.web_search_zhihu_search_path or ""),
                        setting_name="web_search_zhihu_search_path",
                    )
                    if _is_zhihu_playground_endpoint(endpoint):
                        search_payload = self._post_playground_json(
                            client,
                            endpoint,
                            access_secret=access_secret,
                            api_id=ZHIHU_SEARCH_API_ID,
                            payload={"Query": query, "Count": max_results},
                        )
                    else:
                        search_payload = self._get_json(
                            client,
                            endpoint,
                            access_secret=access_secret,
                            params={"Query": query, "Count": str(max_results)},
                        )
                    raw_results = _zhihu_items(search_payload)
                    if include_hot_list:
                        raw_results.extend(
                            self._hot_list_items(
                                client,
                                base_url=base_url,
                                access_secret=access_secret,
                                limit=min(30, max(5, max_results)),
                            )
                        )
        except httpx.TimeoutException as error:
            usage = self._usage(started, error_code="provider.timeout")
            raise WebSearchProviderError(
                "provider.timeout",
                "Zhihu OpenAPI request timed out",
                usage=usage,
            ) from error
        except httpx.HTTPStatusError as error:
            usage = self._usage(started, error_code=_map_provider_http_error(error.response))
            raise WebSearchProviderError(
                usage.error_code or "web_search.zhihu_http_error",
                _extract_http_error_message(error.response, provider_id=self.provider_id),
                usage=usage,
            ) from error
        except httpx.RequestError as error:
            usage = self._usage(started, error_code="provider.network_error")
            raise WebSearchProviderError(
                "provider.network_error",
                "Zhihu OpenAPI request failed",
                usage=usage,
            ) from error

        usage = self._usage(started)
        intent = str(options.get("intent") or "zhihu_research")
        results = _normalize_zhihu_results(raw_results, intent=intent)
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

    def _hot_list_items(
        self,
        client: httpx.Client,
        *,
        base_url: str,
        access_secret: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        cache_key = f"{base_url}:limit:{limit}"
        now = time.time()
        ttl = max(60, int(self.settings.web_search_zhihu_hot_list_cache_ttl_seconds or 3600))
        with _ZHIHU_HOT_LIST_LOCK:
            cached = _ZHIHU_HOT_LIST_CACHE.get(cache_key)
            if cached and cached[0] > now:
                return [dict(item) for item in cached[1]]

        endpoint = self._endpoint(
            base_url,
            str(self.settings.web_search_zhihu_hot_list_path or ""),
            setting_name="web_search_zhihu_hot_list_path",
        )
        if _is_zhihu_playground_endpoint(endpoint):
            hot_payload = self._post_playground_json(
                client,
                endpoint,
                access_secret=access_secret,
                api_id=ZHIHU_HOT_LIST_API_ID,
                payload={"Limit": limit},
                stream=True,
            )
        else:
            hot_payload = self._get_json(
                client,
                endpoint,
                access_secret=access_secret,
                params={"Limit": str(limit)},
            )
        hot_items = _zhihu_hot_items(hot_payload)
        with _ZHIHU_HOT_LIST_LOCK:
            _ZHIHU_HOT_LIST_CACHE[cache_key] = (now + ttl, [dict(item) for item in hot_items])
        return hot_items

    def _get_json(
        self,
        client: httpx.Client,
        endpoint: str,
        *,
        access_secret: str,
        params: dict[str, str],
    ) -> Any:
        response = client.get(
            endpoint,
            params=params,
            headers=self._headers(access_secret=access_secret),
        )
        response.raise_for_status()
        return _json_payload(
            response,
            provider_id=self.provider_id,
            usage=WebSearchProviderUsage(
                provider_id=self.provider_id,
                model_id=self.model_id,
                instance_id=self.instance_id,
                region=str(self.settings.deployment_region or "unspecified"),
                latency_ms=0,
            ),
        )

    def _post_playground_json(
        self,
        client: httpx.Client,
        endpoint: str,
        *,
        access_secret: str,
        api_id: str,
        payload: dict[str, Any],
        stream: bool = False,
    ) -> Any:
        request_body: dict[str, Any] = {"api_id": api_id, "payload": payload}
        if stream:
            request_body["stream"] = True
        response = client.post(
            endpoint,
            headers=self._headers(access_secret=access_secret),
            json=request_body,
        )
        response.raise_for_status()
        return _json_payload(
            response,
            provider_id=self.provider_id,
            usage=WebSearchProviderUsage(
                provider_id=self.provider_id,
                model_id=self.model_id,
                instance_id=self.instance_id,
                region=str(self.settings.deployment_region or "unspecified"),
                latency_ms=0,
            ),
        )

    def _post_playground_direct_answer(
        self,
        client: httpx.Client,
        endpoint: str,
        *,
        access_secret: str,
        query: str,
        source_type: str,
    ) -> dict[str, Any]:
        response = client.post(
            endpoint,
            headers=self._headers(access_secret=access_secret),
            json={
                "api_id": ZHIHU_DIRECT_ANSWER_API_ID,
                "stream": True,
                "payload": {
                    "model": ZHIHU_DIRECT_ANSWER_MODELS[source_type],
                    "messages": [{"role": "user", "content": query}],
                },
            },
        )
        response.raise_for_status()
        return _zhihu_direct_answer_from_response(response)

    def _post_zhida_chat_completion(
        self,
        client: httpx.Client,
        endpoint: str,
        *,
        access_secret: str,
        query: str,
        source_type: str,
    ) -> dict[str, Any]:
        response = client.post(
            endpoint,
            headers=self._headers(access_secret=access_secret),
            json={
                "model": ZHIHU_DIRECT_ANSWER_MODELS[source_type],
                "messages": [{"role": "user", "content": query}],
                "stream": False,
            },
        )
        response.raise_for_status()
        return _zhihu_direct_answer_from_response(response)

    def _headers(self, *, access_secret: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {access_secret}",
            "X-Request-Timestamp": str(int(time.time())),
            "Content-Type": "application/json",
            "App": "web",
        }

    def _endpoint(self, base_url: str, path: str, *, setting_name: str) -> str:
        normalized_path = str(path or "").strip()
        if not normalized_path:
            raise WebSearchProviderError(
                "web_search.zhihu_endpoint_missing",
                f"{setting_name} is required for this Zhihu Open Platform source",
            )
        return f"{base_url}{normalized_path}"

    def _usage(self, started: float, *, error_code: str | None = None) -> WebSearchProviderUsage:
        return WebSearchProviderUsage(
            provider_id=self.provider_id,
            model_id=self.model_id,
            instance_id=self.instance_id,
            region=str(self.settings.deployment_region or "unspecified"),
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
            cost=max(0.0, float(self.settings.web_search_zhihu_cost_per_query or 0.0)),
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
    source_type = _normalize_source_type(input_payload.get("source_type"))
    if intent in ZHIHU_DIRECT_ANSWER_SOURCE_TYPES:
        provider = "zhihu" if provider in {"", "auto"} else provider
        source_type = source_type or intent
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
        "source_type": source_type,
        "include_hot_list": bool(input_payload.get("include_hot_list")),
    }


def _tavily_api_key_pool(settings: Settings) -> list[str]:
    raw_values = [
        str(settings.web_search_tavily_api_keys or ""),
        str(settings.web_search_tavily_api_key or ""),
    ]
    keys: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        for item in re.split(r"[\s,;]+", raw):
            value = item.strip()
            if not value or value in seen:
                continue
            keys.append(value)
            seen.add(value)
    return keys


def _tavily_api_key_labels(settings: Settings, key_count: int) -> list[str]:
    labels = [
        item.strip()
        for item in re.split(r"[\n,;]+", str(settings.web_search_tavily_api_key_labels or ""))
    ]
    if key_count <= 0:
        return []
    return labels[:key_count] + [""] * max(0, key_count - len(labels))


def _select_tavily_api_key(
    api_keys: list[str],
    *,
    labels: list[str] | None = None,
) -> _TavilyApiKeySelection:
    fingerprints = [_hash_tavily_key(item) for item in api_keys]
    pool_id = hashlib.sha256("|".join(fingerprints).encode("utf-8")).hexdigest()[:16]
    now = time.monotonic()
    with _TAVILY_POOL_LOCK:
        start = _TAVILY_POOL_CURSOR.get(pool_id, 0) % len(api_keys)
        selected = start
        for offset in range(len(api_keys)):
            index = (start + offset) % len(api_keys)
            quarantined_until = _TAVILY_POOL_QUARANTINED_UNTIL.get(
                (pool_id, fingerprints[index]), 0.0
            )
            if quarantined_until <= now:
                selected = index
                break
        _TAVILY_POOL_CURSOR[pool_id] = (selected + 1) % len(api_keys)
    return {
        "api_key": api_keys[selected],
        "index": selected,
        "key_count": len(api_keys),
        "fingerprint": fingerprints[selected],
        "pool_id": pool_id,
        "label": labels[selected] if labels and selected < len(labels) else "",
    }


def _quarantine_tavily_api_key(*, pool_id: str, fingerprint: str) -> None:
    with _TAVILY_POOL_LOCK:
        _TAVILY_POOL_QUARANTINED_UNTIL[(pool_id, fingerprint)] = (
            time.monotonic() + TAVILY_KEY_QUARANTINE_SECONDS
        )


def _should_quarantine_tavily_key(error_code: str | None) -> bool:
    return str(error_code or "") in {
        "provider.auth_invalid",
        "provider.rate_limited",
        "provider.timeout",
        "provider.network_error",
        "provider.unavailable",
    }


def _hash_tavily_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _build_provider(
    settings: Settings,
    provider_id: str,
) -> (
    TavilyWebSearchProvider
    | BochaWebSearchProvider
    | ApifyWebSearchProvider
    | ZhihuWebSearchProvider
):
    if provider_id == "tavily":
        return TavilyWebSearchProvider(settings)
    if provider_id == "bocha":
        return BochaWebSearchProvider(settings)
    if provider_id == "apify":
        return ApifyWebSearchProvider(settings)
    if provider_id == "zhihu":
        return ZhihuWebSearchProvider(settings)
    raise WebSearchProviderError(
        "web_search.provider_not_supported",
        "Cloud-managed web search provider is not supported",
    )


def _is_zhihu_playground_endpoint(endpoint: str) -> bool:
    return urlsplit(endpoint).path.rstrip("/") == ZHIHU_PLAYGROUND_INVOKE_PATH


def _is_zhihu_chat_completions_endpoint(endpoint: str) -> bool:
    return urlsplit(endpoint).path.rstrip("/") == "/v1/chat/completions"


def _zhihu_global_filter(recency_days: Any) -> str:
    days = max(0, min(30, _coerce_int(recency_days)))
    if days <= 0:
        return ""
    now = time.time()
    start_date = time.strftime("%Y-%m-%d", time.localtime(now - (days * 86400)))
    end_date = time.strftime("%Y-%m-%d", time.localtime(now))
    return f"publish_time>={start_date} AND publish_time<={end_date}"


def _provider_configured(settings: Settings, provider_id: str) -> bool:
    if provider_id == "tavily":
        return bool(_tavily_api_key_pool(settings))
    if provider_id == "bocha":
        return bool(str(settings.web_search_bocha_api_key or "").strip())
    if provider_id == "apify":
        return bool(
            str(settings.web_search_apify_api_token or "").strip()
            and str(settings.web_search_apify_actor_id or "").strip()
        )
    if provider_id == "zhihu":
        return bool(str(settings.web_search_zhihu_access_secret or "").strip())
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
    source_priority = _source_priority(str(options.get("intent") or "general_research"))
    evidence_pack = _build_search_evidence_pack(
        provider_id=provider_id,
        query=query,
        options=options,
        results=results,
        evidence_policy=evidence_policy,
        evidence_gate=evidence_gate,
    )
    atomic_outputs = _build_atomic_outputs(
        provider_id=provider_id,
        query=query,
        options=options,
        results=results,
        evidence_gate=evidence_gate,
    )
    return {
        "artifact_type": "web_search_results",
        "composition_role": "external_web_evidence",
        "status": "ready",
        "provider": provider_id,
        "provider_mode": str(
            options.get("provider_mode") or options.get("provider") or "cloud_managed"
        ),
        "requested_provider": str(options.get("requested_provider") or ""),
        "intent": str(options.get("intent") or "general_research"),
        "query_hash": _hash_query(query),
        "query_chars": len(query),
        "result_count": len(results),
        "source_priority": source_priority,
        "output_contract": SEARCH_EVIDENCE_PACK_CONTRACT,
        "evidence_gate": evidence_gate,
        "evidence_pack": evidence_pack,
        "atomic_outputs": atomic_outputs,
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


def _build_direct_answer_result_json(
    *,
    provider_id: str,
    query: str,
    options: dict[str, Any],
    answer: dict[str, Any],
    intent: str,
    mode: str,
) -> dict[str, Any]:
    answer_text = _normalize_text(answer.get("answer_text"), limit=4000)
    source_refs = [
        _source_card(ref, provider_id=provider_id)
        for ref in answer.get("source_refs", [])
        if isinstance(ref, dict)
    ]
    status = "ready" if answer_text else "empty"
    source_count = len([item for item in source_refs if str(item.get("url") or "")])
    evidence_gate = {
        "status": "passed" if source_count >= 1 else "insufficient_evidence",
        "min_score": 0.0,
        "required_sources": 1,
        "source_count": source_count,
        "no_hit_policy": "abstain",
        "allows_web_grounded_assertion": source_count >= 1,
        "guidance": (
            "Use direct-answer text only as a grounded preview with source review."
            if source_refs
            else "Treat this direct answer as ungrounded until sources are reviewed."
        ),
    }
    return {
        "artifact_type": "web_search_results",
        "composition_role": "grounded_answer_preview",
        "status": status,
        "provider": provider_id,
        "provider_mode": str(
            options.get("provider_mode") or options.get("provider") or "cloud_managed"
        ),
        "requested_provider": str(options.get("requested_provider") or ""),
        "intent": intent,
        "query_hash": _hash_query(query),
        "query_chars": len(query),
        "result_count": len(source_refs),
        "source_priority": _source_priority(intent),
        "output_contract": GROUNDED_ANSWER_CONTRACT,
        "evidence_gate": evidence_gate,
        "atomic_outputs": {
            "artifact_type": "atomic_knowledge_outputs",
            "contract_versions": sorted(ATOMIC_OUTPUT_CONTRACTS),
            "source_evidence": {
                "artifact_type": "source_evidence_set",
                "contract_version": SOURCE_EVIDENCE_CONTRACT,
                "status": str(evidence_gate.get("status") or "insufficient_evidence"),
                "query_hash": _hash_query(query),
                "provider": provider_id,
                "intent": intent,
                "result_count": len(source_refs),
                "items": source_refs,
                "write_posture": "suggestion_only",
                "direct_wordpress_write": False,
            },
            "topic_candidates": {
                "artifact_type": "topic_candidate_set",
                "contract_version": TOPIC_CANDIDATE_CONTRACT,
                "status": "empty",
                "query_hash": _hash_query(query),
                "provider": provider_id,
                "intent": intent,
                "result_count": 0,
                "items": [],
                "write_posture": "suggestion_only",
                "direct_wordpress_write": False,
            },
            "grounded_answer": {
                "artifact_type": "grounded_answer_preview",
                "contract_version": GROUNDED_ANSWER_CONTRACT,
                "status": status,
                "mode": mode,
                "query_hash": _hash_query(query),
                "answer_text": answer_text,
                "source_refs": source_refs,
                "generation_policy": (
                    "Use as a reviewable direct-answer preview only. Do not insert as "
                    "final article text or publish without local/Core review."
                ),
                "write_posture": "suggestion_only",
                "direct_wordpress_write": False,
            },
        },
        "workflow_metadata": _web_search_workflow_metadata(options),
        "results": source_refs,
        "sources": [
            {
                "title": str(item.get("title") or ""),
                "url": str(item.get("url") or ""),
                "source": str(item.get("source") or provider_id),
            }
            for item in source_refs
        ],
        "write_posture": "suggestion_only",
        "direct_wordpress_write": False,
    }


def _build_direct_answer_degraded_result_json(
    *,
    provider_id: str,
    query: str,
    options: dict[str, Any],
    intent: str,
    mode: str,
    error_code: str,
    error_message: str,
) -> dict[str, Any]:
    result = _build_direct_answer_result_json(
        provider_id=provider_id,
        query=query,
        options=options,
        answer={"answer_text": "", "source_refs": []},
        intent=intent,
        mode=mode,
    )
    status = (
        "provider_rate_limited"
        if error_code == "provider.rate_limited"
        else "provider_unavailable"
    )
    provider_error = {
        "code": error_code,
        "message": _normalize_text(error_message, limit=200),
        "provider": provider_id,
        "retryable": error_code
        in {"provider.rate_limited", "provider.timeout", "provider.unavailable"},
    }
    result["status"] = status
    result["provider_error"] = provider_error
    result["evidence_gate"]["status"] = status
    result["evidence_gate"]["allows_web_grounded_assertion"] = False
    result["evidence_gate"]["guidance"] = (
        "Zhihu direct-answer source is temporarily unavailable; keep this as "
        "a degraded atomic result and retry before using any answer preview."
    )
    result["atomic_outputs"]["grounded_answer"]["status"] = status
    result["atomic_outputs"]["grounded_answer"]["provider_error"] = provider_error
    result["atomic_outputs"]["grounded_answer"]["generation_policy"] = (
        "No answer text was generated because the direct-answer provider was "
        "temporarily unavailable. Do not publish; retry or use source evidence."
    )
    return result


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
    source_preview = str(options.get("intent") or "") == "source_extraction_preview"
    metadata.update(
        {
            "workflow_kind": "fixed_evidence_workflow",
            "triggering_ability": str(options.get("ability_name") or WEB_SEARCH_ABILITY),
            "triggering_contract": WEB_SEARCH_CONTRACT,
            "intent": str(options.get("intent") or "general_research"),
            "cloud_output": (
                "source_extraction_preview" if source_preview else "external_web_evidence"
            ),
            "output_contract": (
                SOURCE_EXTRACTION_PREVIEW_CONTRACT
                if source_preview
                else SEARCH_EVIDENCE_PACK_CONTRACT
            ),
            "write_posture": "suggestion_only",
            "steps": metadata_projection_tokens(metadata.get("steps")),
            "stop_conditions": metadata_projection_tokens(metadata.get("stop_conditions")),
        }
    )
    return metadata


def _extract_source_preview(
    *,
    settings: Settings,
    source_url: str,
    options: dict[str, Any],
) -> WebSearchExecutionResult:
    base_url = str(settings.web_search_jina_reader_base_url or "").strip().rstrip("/")
    if not base_url:
        raise WebSearchProviderError(
            "web_search.reader_not_configured",
            "Cloud-managed source reader is not configured",
        )

    headers = {
        "Accept": "text/plain",
        "X-Return-Format": "markdown",
    }
    api_key = str(settings.web_search_jina_reader_api_key or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    started = time.monotonic()
    usage = WebSearchProviderUsage(
        provider_id="jina_reader",
        model_id="url-reader",
        instance_id="cloud-managed",
        region=str(settings.deployment_region or "unspecified"),
        latency_ms=0,
        cost=0.0,
    )
    try:
        with httpx.Client(
            timeout=float(settings.web_search_jina_reader_timeout_seconds)
        ) as client:
            response = client.get(f"{base_url}/{source_url}", headers=headers)
            response.raise_for_status()
            reader_text = _response_text(
                response,
                max_bytes=MAX_READER_RESPONSE_BYTES,
            )
    except httpx.TimeoutException as error:
        usage.latency_ms = max(0, int((time.monotonic() - started) * 1000))
        usage.error_code = "provider.timeout"
        raise WebSearchProviderError(
            "provider.timeout",
            "Cloud-managed source reader timed out",
            usage=usage,
        ) from error
    except httpx.HTTPError as error:
        usage.latency_ms = max(0, int((time.monotonic() - started) * 1000))
        usage.error_code = "provider.reader_error"
        raise WebSearchProviderError(
            "provider.reader_error",
            "Cloud-managed source reader failed",
            usage=usage,
        ) from error

    usage.latency_ms = max(0, int((time.monotonic() - started) * 1000))
    usage.cost = max(0.0, float(settings.web_search_jina_reader_cost_per_page or 0.0))
    document = _parse_jina_reader_document(reader_text, requested_url=source_url)
    resolved_url = str(document.get("resolved_url") or "")
    try:
        resolved_url = validate_public_source_url(resolved_url)
    except WebSearchContractViolation:
        resolved_url = ""
    url_match = bool(resolved_url) and _source_urls_match(source_url, resolved_url)
    content = str(document.get("content") or "").strip()
    if not url_match:
        content = ""

    status = "ready" if content and url_match else "blocked"
    coverage_level = "partial" if content and url_match else "unavailable"
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest() if content else ""
    words = content.split()
    source_title = (
        _normalize_text(document.get("title"), limit=MAX_RESULT_TITLE_CHARS)
        if url_match
        else ""
    )
    item = {
        "title": source_title,
        "url": resolved_url,
        "snippet": _normalize_text(content, limit=MAX_RESULT_SNIPPET_CHARS),
        "reader_excerpt": content[:MAX_SOURCE_READER_CONTENT_CHARS].rstrip(),
        "reader_status": status,
        "reader_provider": "jina_reader",
        "source": "jina_reader",
        "write_posture": "suggestion_only",
        "direct_wordpress_write": False,
    }
    result_json = {
        "artifact_type": "source_extraction_preview",
        "contract_version": SOURCE_EXTRACTION_PREVIEW_CONTRACT,
        "composition_role": "external_source_extraction_preview",
        "status": status,
        "provider": "jina_reader",
        "provider_mode": "cloud_managed_reader",
        "requested_provider": "",
        "intent": "source_extraction_preview",
        "output_contract": SOURCE_EXTRACTION_PREVIEW_CONTRACT,
        "requested_url": source_url,
        "resolved_url": resolved_url,
        "url_match": "matched" if url_match else "mismatched",
        "title": item["title"],
        "language": str(document.get("language") or "") if url_match else "",
        "published_at": str(document.get("published_at") or "") if url_match else "",
        "content_hash": content_hash,
        "char_count": len(content),
        "word_count": len(words),
        "preview_start": content[:MAX_SOURCE_PREVIEW_CHARS].rstrip(),
        "preview_end": content[-MAX_SOURCE_PREVIEW_CHARS:].lstrip() if content else "",
        "coverage": {
            "level": coverage_level,
            "reader_bounded": True,
            "complete_capture_claimed": False,
            "warnings": (
                [
                    "Reader output is bounded evidence and does not prove complete "
                    "article capture."
                ]
                if content
                else ["Reader output was unavailable or did not match the requested URL."]
            ),
        },
        "content_trust": "untrusted_external_source",
        "prompt_injection_review_required": True,
        "result_count": 1 if content else 0,
        "results": [item] if content else [],
        "sources": (
            [{"title": item["title"], "url": resolved_url, "source": "jina_reader"}]
            if content
            else []
        ),
        "workflow_metadata": _web_search_workflow_metadata(options),
        "write_posture": "suggestion_only",
        "direct_wordpress_write": False,
    }
    return WebSearchExecutionResult(result_json=result_json, usage=usage)


def _parse_jina_reader_document(text: str, *, requested_url: str) -> dict[str, str]:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    metadata: dict[str, str] = {}
    content = normalized
    marker = re.search(r"(?im)^Markdown Content:\s*$", normalized)
    if marker:
        header = normalized[: marker.start()]
        content = normalized[marker.end() :].strip()
        for line in header.splitlines():
            match = re.match(r"^([^:]{1,40}):\s*(.+)$", line.strip())
            if match:
                metadata[match.group(1).strip().lower()] = match.group(2).strip()
    resolved_url = metadata.get("url source", "")
    return {
        "title": metadata.get("title", ""),
        "resolved_url": resolved_url,
        "published_at": metadata.get("published time", ""),
        "language": metadata.get("language", ""),
        "content": content,
    }


def _source_urls_match(requested_url: str, resolved_url: str) -> bool:
    requested = urlsplit(requested_url)
    resolved = urlsplit(resolved_url)
    if str(requested.hostname or "").lower() != str(resolved.hostname or "").lower():
        return False

    def normalized_path(value: str) -> str:
        path = re.sub(r"/+", "/", "/" + str(value or "/").lstrip("/"))
        return "/" if path == "/" else path.rstrip("/")

    return normalized_path(requested.path) == normalized_path(resolved.path)


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
                excerpt = _normalize_text(
                    _response_text(response, max_bytes=MAX_READER_RESPONSE_BYTES),
                    limit=1200,
                )
            except (httpx.TimeoutException, httpx.HTTPError) as error:
                errors.append(
                    {
                        "url_hash": _hash_query(url),
                        "error_code": "provider.reader_error",
                        "message": str(error)[:160],
                    }
                )
                continue
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
    if _response_too_large(response, max_bytes=MAX_PROVIDER_RESPONSE_BYTES):
        usage.error_code = "provider.response_too_large"
        raise WebSearchProviderError(
            "provider.response_too_large",
            f"{provider_id} web search response exceeded the accepted size limit",
            usage=usage,
        )
    try:
        return response.json()
    except ValueError as error:
        usage.error_code = "provider.invalid_response"
        raise WebSearchProviderError(
            "provider.invalid_response",
            f"{provider_id} web search returned invalid JSON",
            usage=usage,
        ) from error


def _response_text(response: httpx.Response, *, max_bytes: int) -> str:
    if _response_too_large(response, max_bytes=max_bytes):
        raise httpx.HTTPError("provider response exceeded the accepted size limit")
    return response.text


def _response_too_large(response: httpx.Response, *, max_bytes: int) -> bool:
    content_length = response.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                return True
        except ValueError:
            pass
    return len(response.content) > max_bytes


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


def _zhihu_items(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("Data")
    if not isinstance(data, dict):
        data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    items = data.get("Items") or data.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _zhihu_direct_answer_from_response(response: httpx.Response) -> dict[str, Any]:
    content_type = str(response.headers.get("content-type") or "")
    if "json" in content_type:
        try:
            return _zhihu_direct_answer(response.json())
        except ValueError:
            pass
    text = _response_text(response, max_bytes=MAX_PROVIDER_RESPONSE_BYTES)
    answer_text = _zhihu_answer_text_from_sse(text)
    if answer_text:
        return {"answer_text": answer_text, "source_refs": []}
    try:
        return _zhihu_direct_answer(json.loads(text))
    except ValueError:
        return {"answer_text": _normalize_text(text, limit=4000), "source_refs": []}


def _zhihu_answer_text_from_sse(text: str) -> str:
    answer_parts: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("error") is not None:
            continue
        choices = event.get("choices")
        if not isinstance(choices, list) or not choices:
            continue
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            continue
        delta = first_choice.get("delta")
        if not isinstance(delta, dict):
            continue
        content = delta.get("content")
        if isinstance(content, str) and content:
            answer_parts.append(content)
    return _normalize_text("".join(answer_parts), limit=4000)


def _zhihu_direct_answer(payload: Any) -> dict[str, Any]:
    openai_answer = _zhihu_openai_answer_text(payload)
    if openai_answer:
        return {"answer_text": openai_answer, "source_refs": []}

    data = payload.get("Data") if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        data = payload.get("data") if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        data = {}

    answer_text = _normalize_text(
        data.get("Answer")
        or data.get("answer")
        or data.get("AnswerText")
        or data.get("answer_text")
        or data.get("Content")
        or data.get("content")
        or data.get("Text")
        or data.get("text")
        or data.get("Summary")
        or data.get("summary"),
        limit=4000,
    )
    if not answer_text and isinstance(payload, dict):
        answer_text = _normalize_text(
            payload.get("Answer")
            or payload.get("answer")
            or payload.get("AnswerText")
            or payload.get("answer_text"),
            limit=4000,
        )

    source_items = (
        data.get("Sources")
        or data.get("sources")
        or data.get("References")
        or data.get("references")
        or data.get("Items")
        or data.get("items")
        or []
    )
    sources = _zhihu_direct_answer_sources(source_items)
    return {
        "answer_text": answer_text,
        "source_refs": sources,
    }


def _zhihu_openai_answer_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return ""
    parts: list[str] = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content:
                parts.append(content)
                continue
        delta = choice.get("delta")
        if isinstance(delta, dict):
            content = delta.get("content")
            if isinstance(content, str) and content:
                parts.append(content)
    return _normalize_text("".join(parts), limit=4000)


def _zhihu_direct_answer_sources(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        title = _normalize_text(
            item.get("Title") or item.get("title") or item.get("Name") or item.get("name"),
            limit=MAX_RESULT_TITLE_CHARS,
        )
        url = _normalize_url(item.get("Url") or item.get("url") or item.get("Link") or "")
        snippet = _normalize_text(
            item.get("ContentText")
            or item.get("Summary")
            or item.get("summary")
            or item.get("Snippet")
            or item.get("snippet"),
            limit=MAX_RESULT_SNIPPET_CHARS,
        )
        if not title and not url and not snippet:
            continue
        dedupe_key = url or f"title:{title}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        sources.append(
            {
                "title": title or "Zhihu direct-answer source",
                "url": url,
                "snippet": snippet,
                "source": _normalize_text(
                    item.get("Source") or item.get("source") or "zhihu",
                    limit=64,
                ),
                "write_posture": "suggestion_only",
                "direct_wordpress_write": False,
            }
        )
    return sources


def _zhihu_hot_items(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("Data")
    if not isinstance(data, dict):
        data = payload.get("data")
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        raw_items = data.get("Items") or data.get("items")
        if not isinstance(raw_items, list):
            return []
        items = raw_items
    else:
        return []
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        updated = dict(item)
        updated["ContentType"] = str(updated.get("ContentType") or "HotList")
        updated["ContentText"] = str(updated.get("Summary") or "")
        updated["RankingScore"] = max(0.0, 1.0 - (index * 0.02))
        updated["source"] = "zhihu_hot_list"
        normalized.append(updated)
    return normalized


def _normalize_zhihu_results(
    raw_results: list[dict[str, Any]],
    *,
    intent: str,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_results:
        title = _normalize_text(raw.get("Title") or raw.get("title"), limit=MAX_RESULT_TITLE_CHARS)
        url = _normalize_url(raw.get("Url") or raw.get("url"))
        snippet = _normalize_text(
            raw.get("ContentText") or raw.get("Summary") or raw.get("summary"),
            limit=MAX_RESULT_SNIPPET_CHARS,
        )
        if not url and not title and not snippet:
            continue
        dedupe_key = url or f"title:{title}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        raw_source = str(raw.get("source") or "")
        if raw_source in {"zhihu_hot_list", "zhihu_global_search"}:
            source = raw_source
        else:
            source = "zhihu"
        normalized.append(
            {
                "title": title or "Untitled Zhihu result",
                "url": url,
                "snippet": snippet,
                "score": _coerce_score(raw.get("RankingScore")),
                "source": source,
                "content_type": _normalize_token(
                    raw.get("ContentType") or raw.get("content_type") or "",
                    limit=48,
                ),
                "content_id": _normalize_token(raw.get("ContentID") or "", limit=96),
                "author_name": _normalize_text(raw.get("AuthorName") or "", limit=120),
                "comment_count": max(0, _coerce_int(raw.get("CommentCount"))),
                "vote_up_count": max(0, _coerce_int(raw.get("VoteUpCount"))),
                "authority_level": _normalize_token(raw.get("AuthorityLevel") or "", limit=16),
                "edit_time": max(0, _coerce_int(raw.get("EditTime"))),
                "thumbnail_url": _normalize_url(raw.get("ThumbnailUrl") or ""),
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
        "zhihu_global_search": "zhihu_global_source_evidence",
        "zhihu_research": "zhihu_audience_question_or_topic_signal",
        "zhihu_hot_topics": "zhihu_hot_topic_candidate",
        "zhida_simple": "fast_direct_answer_preview",
        "zhida_deep": "deep_direct_answer_preview",
        "zhida_deepsearch": "realtime_direct_answer_preview",
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
    source_priority = _source_priority(intent)
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
        "source_priority": source_priority,
        "source_requirements": _source_requirements(intent),
        "sections": _evidence_pack_sections(intent),
        "source_cards": source_cards,
        "citation_candidates": source_cards,
        "guidance": _evidence_pack_guidance(intent, evidence_gate),
        "write_posture": "suggestion_only",
        "direct_wordpress_write": False,
    }


def _build_atomic_outputs(
    *,
    provider_id: str,
    query: str,
    options: dict[str, Any],
    results: list[dict[str, Any]],
    evidence_gate: dict[str, Any],
) -> dict[str, Any]:
    intent = str(options.get("intent") or "general_research")
    source_cards = [_source_card(item, provider_id=provider_id) for item in results]
    topic_candidates = _topic_candidates_from_results(
        results,
        provider_id=provider_id,
        intent=intent,
    )
    source_refs = [
        {
            "title": str(card.get("title") or ""),
            "url": str(card.get("url") or ""),
            "source": str(card.get("source") or provider_id),
        }
        for card in source_cards
        if str(card.get("url") or "")
    ]
    return {
        "artifact_type": "atomic_knowledge_outputs",
        "contract_versions": sorted(ATOMIC_OUTPUT_CONTRACTS),
        "source_evidence": {
            "artifact_type": "source_evidence_set",
            "contract_version": SOURCE_EVIDENCE_CONTRACT,
            "status": str(evidence_gate.get("status") or "insufficient_evidence"),
            "query_hash": _hash_query(query),
            "provider": provider_id,
            "intent": intent,
            "result_count": len(source_cards),
            "items": source_cards,
            "write_posture": "suggestion_only",
            "direct_wordpress_write": False,
        },
        "topic_candidates": {
            "artifact_type": "topic_candidate_set",
            "contract_version": TOPIC_CANDIDATE_CONTRACT,
            "status": "ready" if topic_candidates else "empty",
            "query_hash": _hash_query(query),
            "provider": provider_id,
            "intent": intent,
            "result_count": len(topic_candidates),
            "items": topic_candidates,
            "write_posture": "suggestion_only",
            "direct_wordpress_write": False,
        },
        "grounded_answer": {
            "artifact_type": "grounded_answer_preview",
            "contract_version": GROUNDED_ANSWER_CONTRACT,
            "status": "not_generated",
            "query_hash": _hash_query(query),
            "answer_text": "",
            "source_refs": source_refs,
            "generation_policy": (
                "A downstream answer composer may use source_evidence only when "
                "evidence_gate.status=passed; this Web Search runtime does not "
                "generate final answer text."
            ),
            "write_posture": "suggestion_only",
            "direct_wordpress_write": False,
        },
    }


def _topic_candidates_from_results(
    results: list[dict[str, Any]],
    *,
    provider_id: str,
    intent: str,
) -> list[dict[str, Any]]:
    if intent not in {"zhihu_hot_topics", "zhihu_research"}:
        return []
    candidates: list[dict[str, Any]] = []
    for index, item in enumerate(results):
        title = _normalize_text(item.get("title"), limit=MAX_RESULT_TITLE_CHARS)
        if not title:
            continue
        url = _normalize_url(item.get("url"))
        source = str(item.get("source") or provider_id)
        candidates.append(
            {
                "title": title,
                "url": url,
                "signal": _normalize_text(
                    item.get("snippet"),
                    limit=MAX_RESULT_SNIPPET_CHARS,
                ),
                "source": source,
                "rank": index + 1,
                "score": float(item.get("score") or 0.0),
                "suggested_use": str(item.get("suggested_use") or _suggested_use(intent)),
                "evidence_refs": [url] if url else [],
                "next_action": (
                    "manual_topic_selection_then_focused_research"
                    if intent == "zhihu_hot_topics"
                    else "manual_angle_selection_and_source_review"
                ),
                "write_posture": "suggestion_only",
                "direct_wordpress_write": False,
            }
        )
    return candidates


def _source_card(item: dict[str, Any], *, provider_id: str) -> dict[str, Any]:
    card = {
        "title": _normalize_text(item.get("title"), limit=MAX_RESULT_TITLE_CHARS),
        "url": _normalize_url(item.get("url")),
        "snippet": _normalize_text(item.get("snippet"), limit=MAX_RESULT_SNIPPET_CHARS),
        "source": str(item.get("source") or provider_id),
        "suggested_use": str(item.get("suggested_use") or ""),
        "citation_candidate": bool(item.get("url")),
        "write_posture": "suggestion_only",
        "direct_wordpress_write": False,
    }
    for key in (
        "content_type",
        "content_id",
        "author_name",
        "comment_count",
        "vote_up_count",
        "authority_level",
        "edit_time",
        "thumbnail_url",
    ):
        if key in item and item[key] not in {"", None}:
            card[key] = item[key]
    return card


def _evidence_pack_type(intent: str) -> str:
    return {
        "article_background": "article_background",
        "fact_check": "fact_check",
        "competitor_research": "competitor_snapshot",
        "pricing_snapshot": "pricing_snapshot",
        "product_comparison": "product_comparison",
        "zhihu_global_search": "zhihu_global_evidence",
        "zhihu_research": "zhihu_writing_research",
        "zhihu_hot_topics": "zhihu_hot_topic_pool",
        "zhida_simple": "zhihu_direct_answer_preview",
        "zhida_deep": "zhihu_direct_answer_preview",
        "zhida_deepsearch": "zhihu_direct_answer_preview",
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
        "zhihu_global_search": [
            "global_source_evidence",
            "citation_candidates",
            "authority_notes",
        ],
        "zhihu_research": [
            "zhihu_topic_candidates",
            "audience_questions",
            "citation_candidates",
            "risk_notes",
        ],
        "zhihu_hot_topics": [
            "hot_topic_candidates",
            "topic_selection_signals",
            "manual_review_notes",
        ],
    }.get(intent, ["external_sources", "citation_candidates", "risk_notes"])


def _evidence_pack_guidance(intent: str, evidence_gate: dict[str, Any]) -> str:
    if str(evidence_gate.get("status") or "") != "passed":
        return (
            "Treat this pack as insufficient evidence and ask for manual review before "
            "making current factual claims."
        )
    return {
        "article_background": (
            "Use as a pre-writing background pack. Cite sources for current claims "
            "and keep final writes local-governed."
        ),
        "fact_check": (
            "Use as supporting evidence for claim review. Prefer official or primary "
            "sources and do not mark unsupported claims as verified."
        ),
        "competitor_research": (
            "Use as a lightweight competitor snapshot, not a durable competitor database."
        ),
        "pricing_snapshot": (
            "Use as a point-in-time pricing snapshot. Prefer official pricing or "
            "documentation pages and re-check before publishing pricing claims."
        ),
        "product_comparison": (
            "Use as a lightweight comparison input. Confirm important claims manually "
            "before publishing."
        ),
        "zhihu_research": (
            "Use Zhihu results as pre-writing research, audience-question signals, "
            "and citation candidates. Do not copy or rewrite source content as final article text."
        ),
        "zhihu_hot_topics": (
            "Use Zhihu hot-list items as topic-selection signals only. Choose topics manually, "
            "then run focused research before drafting."
        ),
        "zhihu_global_search": (
            "Use Zhihu global-search results as source evidence and citation candidates. "
            "Prefer primary or authoritative sources for publishable factual claims."
        ),
        "zhida_simple": (
            "Use direct-answer output only as a fast preview. Review sources before using it "
            "in FAQ, AEO, or article-planning surfaces."
        ),
        "zhida_deep": (
            "Use direct-answer output only as a deep preview. Preserve source review and local "
            "approval before any write-like result."
        ),
        "zhida_deepsearch": (
            "Use direct-answer output only as a real-time research preview. Re-check sources "
            "before publishing time-sensitive claims."
        ),
    }.get(
        intent,
        (
            "Use returned web sources as external grounding evidence. Keep conclusions "
            "suggestion-only."
        ),
    )


def _provider_query(query: str, intent: str) -> str:
    hint = _provider_query_hint(intent)
    if not hint:
        return query
    query_lower = query.lower()
    if any(term in query_lower for term in _provider_query_marker_terms(intent)):
        return query
    return _normalize_text(f"{query} {hint}", limit=MAX_QUERY_CHARS)


def _provider_query_hint(intent: str) -> str:
    return {
        "fact_check": "official primary source documentation source of record",
        "pricing_snapshot": "official pricing page pricing documentation",
    }.get(intent, "")


def _provider_query_marker_terms(intent: str) -> tuple[str, ...]:
    return {
        "fact_check": (
            "official primary source",
            "official documentation",
            "source of record",
        ),
        "pricing_snapshot": (
            "official pricing",
            "official billing",
            "pricing documentation",
        ),
    }.get(intent, ())


def _source_priority(intent: str) -> str:
    return {
        "fact_check": "official_or_primary_sources",
        "pricing_snapshot": "official_pricing_or_docs",
        "zhihu_global_search": "zhihu_web_and_authoritative_sources",
        "zhida_deepsearch": "realtime_multi_source_evidence",
    }.get(intent, "external_sources")


def _source_requirements(intent: str) -> list[str]:
    return {
        "fact_check": [
            "Prefer official, primary, standards, documentation, or source-of-record pages.",
            "Use secondary sources only as context unless they directly cite a primary source.",
        ],
        "pricing_snapshot": [
            "Prefer official pricing, billing, plan, documentation, or changelog pages.",
            (
                "Treat third-party pricing pages as fallback context and re-check "
                "official pages before publishing."
            ),
        ],
        "zhihu_research": [
            "Use Zhihu links as source candidates and audience-demand signals.",
            "Do not copy source wording into the final article without review and attribution.",
        ],
        "zhihu_hot_topics": [
            "Use hot-list items as trend and topic-selection signals.",
            "Run focused research and source verification before drafting or publishing.",
        ],
        "zhihu_global_search": [
            "Use Zhihu global-search output as source evidence for broad web research.",
            "Prefer authoritative or primary sources for publishable factual claims.",
        ],
        "zhida_simple": [
            "Use the direct answer as a fast answer preview, not final article text.",
            "Review source references before using factual claims.",
        ],
        "zhida_deep": [
            "Use the direct answer as a professional analysis preview, not final article text.",
            "Preserve evidence references for local review.",
        ],
        "zhida_deepsearch": [
            "Use the direct answer as a real-time research preview, not final article text.",
            "Re-check time-sensitive source references before publishing.",
        ],
    }.get(intent, [])


def _normalize_source_type(value: Any) -> str:
    source_type = _normalize_token(value, limit=48)
    if source_type in {
        "zhihu_search",
        "zhihu_hot_list",
        "zhihu_research",
        "zhihu_global_search",
        *ZHIHU_DIRECT_ANSWER_SOURCE_TYPES,
    }:
        return source_type
    return ""


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


def _extract_http_error_message(
    response: httpx.Response,
    *,
    provider_id: str = "web search provider",
) -> str:
    provider_label = provider_id.replace("_", " ").title()
    if _response_too_large(response, max_bytes=MAX_PROVIDER_RESPONSE_BYTES):
        return f"{provider_label} web search failed with HTTP {response.status_code}"
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if isinstance(payload, dict):
        message = str(payload.get("message") or payload.get("error") or "").strip()
        if message:
            return message[:200]
    return f"{provider_label} web search failed with HTTP {response.status_code}"
