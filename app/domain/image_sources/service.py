from __future__ import annotations

import hashlib
import random
import time
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import unquote, urlsplit

import httpx

from app.core.config import Settings
from app.domain.image_generation.contracts import (
    IMAGE_GENERATION_CLOUD_ABILITY,
    IMAGE_GENERATION_CONTRACT,
    IMAGE_GENERATION_EXECUTION_KIND,
    IMAGE_GENERATION_PROFILE_ID,
    IMAGE_GENERATION_RESULT_CONTRACT,
)
from app.domain.image_sources.contracts import (
    ALLOWED_IMAGE_SOURCE_ORIENTATIONS,
    ALLOWED_IMAGE_SOURCE_PROVIDERS,
    IMAGE_CANDIDATE_CONTRACT,
    ImageSourceContractViolation,
    coerce_positive_int,
    validate_image_source_runtime_contract,
)

MAX_QUERY_CHARS = 300
MAX_TEXT_CHARS = 300
MAX_VISUAL_CONTEXT_CHARS = 600
MAX_PROVIDER_RESULTS = 30
MAX_PROVIDER_RESPONSE_BYTES = 2_000_000
AUTO_PROVIDER_ORDER = ("unsplash", "pixabay", "pexels")


@dataclass(slots=True)
class ImageSourceProviderUsage:
    provider_id: str
    model_id: str
    instance_id: str
    region: str
    latency_ms: int
    cost: float = 0.0
    error_code: str | None = None


@dataclass(slots=True)
class ImageSourceExecutionResult:
    result_json: dict[str, Any]
    usage: ImageSourceProviderUsage


class ImageSourceProviderError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        usage: ImageSourceProviderUsage | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.usage = usage


class ImageSourceService:
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
        site_knowledge_context: dict[str, Any] | None = None,
        llm_prompt_plan: dict[str, Any] | None = None,
    ) -> ImageSourceExecutionResult:
        validate_image_source_runtime_contract(
            ability_name=ability_name,
            contract_version=contract_version,
            input_payload=input_payload,
        )
        query = _image_source_provider_query(input_payload)
        if not query:
            raise ImageSourceContractViolation(
                "image_source.query_required",
                "image source query is required",
            )
        options = _build_options(
            input_payload,
            site_knowledge_context=site_knowledge_context,
            llm_prompt_plan=llm_prompt_plan,
        )
        provider_id = _resolve_provider(self.settings, str(options.get("provider") or "auto"))
        provider = _build_provider(provider_id, self.settings)
        return provider.search(query=query, options=options, site_id=site_id, run_id=run_id)


class _BaseImageProvider:
    provider_id = ""
    model_id = "image-source-search"
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
    ) -> ImageSourceExecutionResult:
        raise NotImplementedError

    def _usage(self, started: float, *, error_code: str | None = None) -> ImageSourceProviderUsage:
        return ImageSourceProviderUsage(
            provider_id=self.provider_id,
            model_id=self.model_id,
            instance_id=self.instance_id,
            region=str(self.settings.deployment_region or "unspecified"),
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
            cost=max(0.0, float(self.settings.image_source_cost_per_query or 0.0)),
            error_code=error_code,
        )

    def _request_json(
        self,
        *,
        started: float,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            timeout_seconds = float(self.settings.image_source_timeout_seconds)
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.request(
                    method,
                    url,
                    headers=headers or {},
                    params=params or {},
                )
                response.raise_for_status()
        except httpx.TimeoutException as error:
            raise ImageSourceProviderError(
                "provider.timeout",
                f"{self.provider_id} image source search timed out",
                usage=self._usage(started, error_code="provider.timeout"),
            ) from error
        except httpx.HTTPStatusError as error:
            error_code = _map_http_error(error.response)
            raise ImageSourceProviderError(
                error_code,
                _extract_http_error_message(error.response),
                usage=self._usage(started, error_code=error_code),
            ) from error
        except httpx.RequestError as error:
            raise ImageSourceProviderError(
                "provider.network_error",
                f"{self.provider_id} image source request failed",
                usage=self._usage(started, error_code="provider.network_error"),
            ) from error

        try:
            if _response_too_large(response, max_bytes=MAX_PROVIDER_RESPONSE_BYTES):
                raise ValueError("provider response exceeded the accepted size limit")
            payload = response.json()
        except ValueError as error:
            raise ImageSourceProviderError(
                "provider.invalid_response",
                f"{self.provider_id} image source returned invalid JSON",
                usage=self._usage(started, error_code="provider.invalid_response"),
            ) from error
        return payload if isinstance(payload, dict) else {}


class UnsplashImageSourceProvider(_BaseImageProvider):
    provider_id = "unsplash"

    def search(
        self,
        *,
        query: str,
        options: dict[str, Any],
        site_id: str,
        run_id: str,
    ) -> ImageSourceExecutionResult:
        api_key = str(self.settings.image_source_unsplash_access_key or "").strip()
        if not api_key:
            raise ImageSourceProviderError(
                "image_source.unsplash_key_missing",
                "Cloud-managed Unsplash access key is not configured",
            )
        base_url = str(self.settings.image_source_unsplash_base_url or "").strip().rstrip("/")
        params: dict[str, Any] = {
            "query": query,
            "per_page": int(options["per_page"]),
        }
        if options.get("orientation") in {"landscape", "portrait", "squarish"}:
            params["orientation"] = options["orientation"]
        if options.get("color"):
            params["color"] = options["color"]
        started = time.monotonic()
        payload = self._request_json(
            started=started,
            method="GET",
            url=f"{base_url}/search/photos",
            headers={"Authorization": f"Client-ID {api_key}"},
            params=params,
        )
        candidates = [_normalize_unsplash(item) for item in _list(payload.get("results"))]
        return _build_result(
            provider_id=self.provider_id,
            auto_strategy=str(self.settings.image_source_auto_strategy or "first_available"),
            query=query,
            options=options,
            candidates=candidates,
            usage=self._usage(started),
        )


class PixabayImageSourceProvider(_BaseImageProvider):
    provider_id = "pixabay"

    def search(
        self,
        *,
        query: str,
        options: dict[str, Any],
        site_id: str,
        run_id: str,
    ) -> ImageSourceExecutionResult:
        api_key = str(self.settings.image_source_pixabay_api_key or "").strip()
        if not api_key:
            raise ImageSourceProviderError(
                "image_source.pixabay_key_missing",
                "Cloud-managed Pixabay API key is not configured",
            )
        base_url = str(self.settings.image_source_pixabay_base_url or "").strip()
        if base_url and not base_url.endswith("/"):
            base_url = f"{base_url}/"
        params: dict[str, Any] = {
            "key": api_key,
            "q": query,
            "per_page": int(options["per_page"]),
            "image_type": "photo",
            "safesearch": "true",
        }
        orientation = options.get("orientation")
        if orientation == "landscape":
            params["orientation"] = "horizontal"
        if orientation == "portrait":
            params["orientation"] = "vertical"
        started = time.monotonic()
        payload = self._request_json(
            started=started,
            method="GET",
            url=base_url,
            params=params,
        )
        candidates = [_normalize_pixabay(item) for item in _list(payload.get("hits"))]
        return _build_result(
            provider_id=self.provider_id,
            auto_strategy=str(self.settings.image_source_auto_strategy or "first_available"),
            query=query,
            options=options,
            candidates=candidates,
            usage=self._usage(started),
        )


class PexelsImageSourceProvider(_BaseImageProvider):
    provider_id = "pexels"

    def search(
        self,
        *,
        query: str,
        options: dict[str, Any],
        site_id: str,
        run_id: str,
    ) -> ImageSourceExecutionResult:
        api_key = str(self.settings.image_source_pexels_api_key or "").strip()
        if not api_key:
            raise ImageSourceProviderError(
                "image_source.pexels_key_missing",
                "Cloud-managed Pexels API key is not configured",
            )
        base_url = str(self.settings.image_source_pexels_base_url or "").strip().rstrip("/")
        params: dict[str, Any] = {
            "query": query,
            "per_page": int(options["per_page"]),
        }
        if options.get("orientation") in {"landscape", "portrait", "square"}:
            params["orientation"] = options["orientation"]
        started = time.monotonic()
        payload = self._request_json(
            started=started,
            method="GET",
            url=f"{base_url}/search",
            headers={"Authorization": api_key},
            params=params,
        )
        candidates = [_normalize_pexels(item) for item in _list(payload.get("photos"))]
        return _build_result(
            provider_id=self.provider_id,
            auto_strategy=str(self.settings.image_source_auto_strategy or "first_available"),
            query=query,
            options=options,
            candidates=candidates,
            usage=self._usage(started),
        )


def _build_options(
    input_payload: dict[str, Any],
    *,
    site_knowledge_context: dict[str, Any] | None = None,
    llm_prompt_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider = str(input_payload.get("provider") or "auto").strip().lower()
    if provider not in ALLOWED_IMAGE_SOURCE_PROVIDERS:
        provider = "auto"
    orientation = str(input_payload.get("orientation") or "").strip().lower()
    if orientation == "horizontal":
        orientation = "landscape"
    if orientation == "vertical":
        orientation = "portrait"
    if orientation not in ALLOWED_IMAGE_SOURCE_ORIENTATIONS:
        orientation = ""
    latency_mode = _image_source_latency_mode(input_payload)
    raw_visual_context = _dict(input_payload.get("visual_context"))
    return {
        "provider": provider,
        "per_page": coerce_positive_int(
            input_payload.get("per_page"),
            default=8,
            maximum=MAX_PROVIDER_RESULTS,
        ),
        "orientation": orientation,
        "color": _normalize_token(input_payload.get("color"), limit=40),
        "purpose": _normalize_token(
            input_payload.get("purpose"),
            limit=80,
        )
        or "image_reference_candidate",
        "locale": _normalize_locale(
            input_payload.get("locale") or raw_visual_context.get("locale")
        ),
        "latency_mode": latency_mode,
        "enhancement_mode": _normalize_token(input_payload.get("enhancement_mode"), limit=40),
        "visual_context": _normalize_visual_context(raw_visual_context),
        "site_knowledge_context": _normalize_site_knowledge_context(site_knowledge_context),
        "llm_prompt_plan": _normalize_llm_prompt_plan(llm_prompt_plan),
    }


def _image_source_latency_mode(input_payload: dict[str, Any]) -> str:
    visual_context = _dict(input_payload.get("visual_context"))
    latency_mode = (
        str(input_payload.get("latency_mode") or visual_context.get("latency_mode") or "")
        .strip()
        .lower()
    )
    return latency_mode if latency_mode == "fast_first" else "complete"


def _image_source_provider_query(input_payload: dict[str, Any]) -> str:
    query = _normalize_text(input_payload.get("query"), limit=MAX_QUERY_CHARS)
    if _image_source_latency_mode(input_payload) != "fast_first":
        return query

    visual_context = _dict(input_payload.get("visual_context"))
    parts = [
        visual_context.get("manual_query"),
        visual_context.get("fallback_query"),
        input_payload.get("query"),
        visual_context.get("title"),
        visual_context.get("selected_text"),
        visual_context.get("selected_block_text"),
        visual_context.get("excerpt"),
    ]
    for part in parts:
        candidate = _normalize_text(part, limit=MAX_VISUAL_CONTEXT_CHARS)
        if candidate:
            visual_query = _visual_query_from_context(candidate)
            if visual_query:
                return _normalize_text(visual_query, limit=180)
            return _normalize_text(candidate, limit=180)
    return query


def _resolve_provider(settings: Settings, requested_provider: str) -> str:
    configured_provider = str(settings.image_source_provider or "disabled").strip().lower()
    if configured_provider == "disabled":
        raise ImageSourceProviderError(
            "image_source.provider_not_configured",
            "Cloud-managed image source provider is not configured",
        )
    if requested_provider not in {"auto", "cloud"}:
        configured_provider = requested_provider
    elif configured_provider == "auto":
        configured_provider = _resolve_auto_provider(settings)
    if configured_provider not in {"unsplash", "pixabay", "pexels"}:
        raise ImageSourceProviderError(
            "image_source.provider_not_configured",
            "Cloud-managed image source provider is not configured",
        )
    return configured_provider


def _resolve_auto_provider(settings: Settings) -> str:
    available_provider_ids = [
        provider_id
        for provider_id in AUTO_PROVIDER_ORDER
        if _provider_has_key(settings, provider_id)
    ]
    strategy = str(settings.image_source_auto_strategy or "first_available").strip().lower()
    if strategy == "random" and available_provider_ids:
        return random.choice(available_provider_ids)
    return available_provider_ids[0] if available_provider_ids else "auto"


def _build_provider(provider_id: str, settings: Settings) -> _BaseImageProvider:
    if provider_id == "pixabay":
        return PixabayImageSourceProvider(settings)
    if provider_id == "pexels":
        return PexelsImageSourceProvider(settings)
    return UnsplashImageSourceProvider(settings)


def _provider_has_key(settings: Settings, provider_id: str) -> bool:
    if provider_id == "unsplash":
        return bool(str(settings.image_source_unsplash_access_key or "").strip())
    if provider_id == "pixabay":
        return bool(str(settings.image_source_pixabay_api_key or "").strip())
    if provider_id == "pexels":
        return bool(str(settings.image_source_pexels_api_key or "").strip())
    return False


def _normalize_unsplash(raw: Any) -> dict[str, Any]:
    item = _dict(raw)
    urls = _dict(item.get("urls"))
    links = _dict(item.get("links"))
    user = _dict(item.get("user"))
    photographer = _normalize_text(user.get("name"), limit=MAX_TEXT_CHARS)
    source_url = _normalize_url(links.get("html"))
    user_links = _dict(user.get("links"))
    return _candidate(
        provider="unsplash",
        candidate_id=str(item.get("id") or ""),
        description=_normalize_text(
            item.get("alt_description") or item.get("description"),
            limit=MAX_TEXT_CHARS,
        ),
        download_url=_normalize_url(urls.get("regular")),
        thumbnail_url=_normalize_url(urls.get("thumb") or urls.get("small")),
        source_url=source_url,
        photographer=photographer,
        photographer_url=_normalize_url(user_links.get("html")),
        attribution=_attribution(
            provider="Unsplash",
            photographer=photographer,
            source_url=source_url,
        ),
        download_location=_normalize_url(links.get("download_location")),
    )


def _normalize_pixabay(raw: Any) -> dict[str, Any]:
    item = _dict(raw)
    photographer = _normalize_text(item.get("user"), limit=MAX_TEXT_CHARS)
    source_url = _normalize_url(item.get("pageURL"))
    return _candidate(
        provider="pixabay",
        candidate_id=str(item.get("id") or ""),
        description=_normalize_text(item.get("tags"), limit=MAX_TEXT_CHARS),
        download_url=_normalize_url(item.get("largeImageURL") or item.get("webformatURL")),
        thumbnail_url=_normalize_url(item.get("previewURL") or item.get("webformatURL")),
        source_url=source_url,
        photographer=photographer,
        photographer_url="",
        attribution=_attribution(
            provider="Pixabay",
            photographer=photographer,
            source_url=source_url,
        ),
        download_location="",
    )


def _normalize_pexels(raw: Any) -> dict[str, Any]:
    item = _dict(raw)
    src = _dict(item.get("src"))
    photographer = _normalize_text(item.get("photographer"), limit=MAX_TEXT_CHARS)
    source_url = _normalize_url(item.get("url"))
    return _candidate(
        provider="pexels",
        candidate_id=str(item.get("id") or ""),
        description=_normalize_text(item.get("alt"), limit=MAX_TEXT_CHARS),
        download_url=_normalize_url(src.get("large") or src.get("original")),
        thumbnail_url=_normalize_url(src.get("tiny") or src.get("medium")),
        source_url=source_url,
        photographer=photographer,
        photographer_url=_normalize_url(item.get("photographer_url")),
        attribution=_attribution(
            provider="Pexels",
            photographer=photographer,
            source_url=source_url,
        ),
        download_location="",
    )


def _candidate(
    *,
    provider: str,
    candidate_id: str,
    description: str,
    download_url: str,
    thumbnail_url: str,
    source_url: str,
    photographer: str,
    photographer_url: str,
    attribution: str,
    download_location: str,
) -> dict[str, Any]:
    stable_id = candidate_id or _hash_text(download_url or source_url)
    suggested_filename = _suggested_candidate_filename(
        provider=provider,
        stable_id=stable_id,
        download_url=download_url,
        source_url=source_url,
    )
    return {
        "contract_version": IMAGE_CANDIDATE_CONTRACT,
        "id": stable_id,
        "provider": provider,
        "provider_origin": "cloud",
        "source_type": "stock",
        "description": description,
        "alt_description": description,
        "download_url": download_url,
        "regular_url": download_url,
        "thumbnail_url": thumbnail_url,
        "thumb_url": thumbnail_url,
        "source_url": source_url,
        "html_url": source_url,
        "download_location": download_location,
        "suggested_filename": suggested_filename,
        "filename_basis": {
            "owner": "wordpress_write_ability_final",
            "strategy": "provider_candidate_id",
            "final_sanitize_unique_required": True,
        },
        "photographer": photographer,
        "photographer_url": photographer_url,
        "attribution": attribution,
        "license_review_status": "required",
        "requires_human_license_review": True,
        "warnings": [
            "Review provider license, attribution, and usage restrictions before adoption."
        ],
        "provenance": {
            "provider": provider,
            "provider_origin": "cloud",
            "source_type": "stock",
            "source_url": source_url,
            "download_location": download_location,
            "photographer": photographer,
        },
        "write_posture": "suggestion_only",
        "direct_wordpress_write": False,
    }


def _build_result(
    *,
    provider_id: str,
    auto_strategy: str,
    query: str,
    options: dict[str, Any],
    candidates: list[dict[str, Any]],
    usage: ImageSourceProviderUsage,
) -> ImageSourceExecutionResult:
    candidates = [
        item for item in candidates if item.get("download_url") or item.get("source_url")
    ][: int(options["per_page"])]
    query_hash = _hash_text(query)
    visual_brief = _build_visual_brief(query=query, options=options)
    prompt_candidates = _build_prompt_candidates(
        query=query,
        options=options,
        visual_brief=visual_brief,
    )
    ai_generation_handoff = _build_ai_generation_handoff(
        query_hash=query_hash,
        options=options,
        prompt_candidates=prompt_candidates,
    )
    result_json = {
        "artifact_type": "image_source_candidates",
        "composition_role": "image_source_candidates",
        "status": "ready",
        "provider": "magick_ai_cloud",
        "provider_mode": provider_id,
        "requested_provider_mode": str(options.get("provider") or "auto"),
        "resolved_provider": provider_id,
        "auto_strategy": auto_strategy,
        "candidate_contract_version": IMAGE_CANDIDATE_CONTRACT,
        "query_hash": query_hash,
        "query_chars": len(query),
        "active_sources": [{"provider": provider_id, "count": len(candidates)}],
        "provider_errors": [],
        "visual_brief": visual_brief,
        "optimized_query": visual_brief["primary_query"],
        "alternate_queries": visual_brief["alternate_queries"],
        "query_suggestions": visual_brief["query_suggestions"],
        "prompt_candidates": prompt_candidates,
        "images": candidates,
        "candidates": candidates,
        "ai_generation_handoff": ai_generation_handoff,
        "handoff": {
            "candidate_contract": IMAGE_CANDIDATE_CONTRACT,
            "final_writes": "core_proposal_required",
            "direct_wordpress_write": False,
            "available_actions": [ai_generation_handoff],
        },
        "write_posture": "suggestion_only",
        "direct_wordpress_write": False,
    }
    return ImageSourceExecutionResult(result_json=result_json, usage=usage)


def _build_ai_generation_handoff(
    *,
    query_hash: str,
    options: dict[str, Any],
    prompt_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "action_id": "ai_generate_image",
        "action_kind": "runtime_handoff",
        "trigger": "manual_user_action",
        "label": "ai_generate",
        "runtime": {
            "ability_name": IMAGE_GENERATION_CLOUD_ABILITY,
            "contract_version": IMAGE_GENERATION_CONTRACT,
            "profile_id": IMAGE_GENERATION_PROFILE_ID,
            "execution_kind": IMAGE_GENERATION_EXECUTION_KIND,
            "execution_pattern": "inline",
            "ability_family": "vision",
            "data_classification": "internal",
            "storage_mode": "result_only",
            "policy": {"allow_fallback": False},
        },
        "input_contract": IMAGE_GENERATION_CONTRACT,
        "result_contract": IMAGE_GENERATION_RESULT_CONTRACT,
        "input_defaults": {
            "contract_version": IMAGE_GENERATION_CONTRACT,
            "aspect_ratio": _default_generation_aspect_ratio(str(options.get("orientation") or "")),
            "resolution": "high",
            "response_format": "url",
            "n": 1,
        },
        "required_local_fields": ["prompt"],
        "local_prompt_sources": [
            "cloud_llm_prompt_planner.prompt_candidates",
            "cloud_visual_brief.prompt_candidates",
            "image_source_runtime_input.query",
            "post_title",
            "post_excerpt",
            "selected_text_context",
        ],
        "prompt_prefill_plan": _build_prompt_prefill_plan(options),
        "prompt_candidates": prompt_candidates,
        "batch_generation_plan": _build_batch_generation_plan(options),
        "source_context": {
            "query_hash": query_hash,
            "purpose": str(options.get("purpose") or "image_reference_candidate"),
            "orientation": str(options.get("orientation") or ""),
        },
        "write_posture": "suggestion_only",
        "direct_wordpress_write": False,
    }


def _build_visual_brief(*, query: str, options: dict[str, Any]) -> dict[str, Any]:
    context = _dict(options.get("visual_context"))
    site_context = _dict(options.get("site_knowledge_context"))
    llm_prompt_plan = _dict(options.get("llm_prompt_plan"))
    evidence_refs = _site_context_evidence_refs(site_context)
    site_context_status = str(site_context.get("status") or "not_requested")
    llm_status = str(llm_prompt_plan.get("status") or "not_requested")
    latency_mode = str(options.get("latency_mode") or "complete").strip().lower()
    use_site_knowledge_vectors = site_context_status not in {"deferred", "skipped"}
    selected_context = _normalize_text(
        context.get("selected_text") or context.get("selected_block_text"),
        limit=MAX_VISUAL_CONTEXT_CHARS,
    )
    article_title = _normalize_text(context.get("title"), limit=160)
    excerpt = _normalize_text(context.get("excerpt"), limit=240)
    image_mode = _normalize_token(context.get("image_mode"), limit=40) or "featured_image"
    subject = selected_context or article_title or excerpt
    primary_query = _visual_query_from_context(subject or "editorial article illustration")
    alternate_queries = _dedupe_texts(
        [
            primary_query,
            _visual_query_from_context(article_title),
            _visual_query_from_context(excerpt),
        ],
        limit=4,
    )
    visual_intent = (
        "Use the selected paragraph and public site context as semantic guidance; "
        "translate the idea into an editorial image instead of rendering the paragraph text."
        if selected_context
        else "Translate the article context into a concrete editorial image direction."
    )
    brief = {
        "status": "ready",
        "artifact_type": "paragraph_image_visual_brief.v1",
        "composition_role": "paragraph_image_prompt_planning",
        "visual_intent": visual_intent,
        "primary_query": primary_query,
        "alternate_queries": alternate_queries,
        "query_suggestions": alternate_queries[:3],
        "source_context": {
            "image_mode": image_mode,
            "selected_paragraph_used": bool(selected_context),
            "site_context_status": site_context_status,
            "site_context_owner": "cloud_site_knowledge",
            "site_context_result_count": len(evidence_refs),
            "llm_prompt_planner_status": llm_status,
            "latency_mode": latency_mode or "complete",
        },
        "site_context": {
            "status": site_context_status,
            "intent": str(site_context.get("intent") or "image_context"),
            "evidence_gate": _dict(site_context.get("evidence_gate")),
            "rerank": _dict(site_context.get("rerank")),
            "evidence_refs": evidence_refs,
        },
        "llm_prompt_planner": {
            "status": llm_status,
            "profile_id": str(llm_prompt_plan.get("profile_id") or ""),
            "provider_id": str(llm_prompt_plan.get("provider_id") or ""),
            "model_id": str(llm_prompt_plan.get("model_id") or ""),
            "candidate_count": len(_list(llm_prompt_plan.get("prompt_candidates"))),
            "fallback": str(llm_prompt_plan.get("fallback") or ""),
        },
        "avoid": [
            "visible text",
            "article wording as image copy",
            "logos",
            "watermarks",
            "screenshots or UI panels",
        ],
        "evidence_policy": {
            "owner": "cloud_runtime",
            "use_site_knowledge_vectors": use_site_knowledge_vectors,
            "evidence_count": len(evidence_refs),
            "direct_wordpress_write": False,
        },
        "site_context_status": site_context_status,
        "llm_prompt_planner_status": llm_status,
        "rerank_status": str(_dict(site_context.get("rerank")).get("status") or "not_requested"),
        "write_posture": "suggestion_only",
        "direct_wordpress_write": False,
    }
    if _is_zh_cn_locale(options.get("locale")):
        brief.update(
            {
                "localized_title": "可选配图方向",
                "localized_summary": (
                    "已根据选中段落和文章上下文生成可审核的配图方向。"
                    if selected_context
                    else "已根据文章上下文生成可审核的配图方向。"
                ),
                "localized_intent": (
                    "把选中段落转译成编辑配图方向，不在图片中呈现原文。"
                    if selected_context
                    else "把文章主题转译成具体的编辑配图方向。"
                ),
            }
        )
    return brief


def _build_prompt_candidates(
    *,
    query: str,
    options: dict[str, Any],
    visual_brief: dict[str, Any],
) -> list[dict[str, Any]]:
    llm_prompt_plan = _dict(options.get("llm_prompt_plan"))
    llm_candidates = _prompt_candidates_from_llm_plan(
        llm_prompt_plan,
        evidence_refs=_site_context_evidence_refs(_dict(options.get("site_knowledge_context"))),
        locale=str(options.get("locale") or ""),
    )
    if llm_candidates:
        return llm_candidates

    context = _dict(options.get("visual_context"))
    selected_context = _normalize_text(
        context.get("selected_text") or context.get("selected_block_text"),
        limit=MAX_VISUAL_CONTEXT_CHARS,
    )
    article_title = _normalize_text(context.get("title"), limit=160)
    excerpt = _normalize_text(context.get("excerpt"), limit=240)
    subject = selected_context or article_title or excerpt or "the article section"
    site_evidence = _site_context_prompt_evidence(_dict(options.get("site_knowledge_context")))
    primary_query = str(visual_brief.get("primary_query") or query)
    aspect_ratio = _default_generation_aspect_ratio(str(options.get("orientation") or ""))
    evidence_sentence = (
        f" Related site context: {site_evidence}. "
        if site_evidence
        else " Related site context was unavailable or insufficient; avoid unsupported site-specific claims. "
    )
    prompts = [
        (
            "editorial_scene",
            "Editorial scene",
            "editorial_scene",
            "Concrete editorial scene",
            "Best when the selected paragraph needs a natural article image that illustrates the idea without turning it into a diagram.",
            (
                "Create an original editorial image for a WordPress article. "
                f"Semantic context: {subject}. "
                f"{evidence_sentence}"
                f"Visual direction: {primary_query}. "
                "Translate the idea into a concrete scene or metaphor. "
                f"Composition: {aspect_ratio}. "
                "Style: realistic editorial photo illustration, natural light, high quality. "
                "No visible text, letters, numbers, labels, logos, watermarks, screenshots, UI panels, or copied article wording."
            ),
        ),
        (
            "conceptual_metaphor",
            "Conceptual metaphor",
            "conceptual_metaphor",
            "Abstract idea through objects",
            "Best for SEO/AEO/GEO or strategy concepts that are too abstract for literal photography.",
            (
                "Create an original conceptual editorial image for the selected paragraph. "
                f"Topic context: {subject}. "
                f"{evidence_sentence}"
                "Show the underlying idea through objects, spatial relationships, and human-scale context, not through written words. "
                f"Composition: {aspect_ratio}. "
                "Clean professional style, natural light, no text, no logos, no interface mockups, no watermarks."
            ),
        ),
        (
            "workspace_detail",
            "Workspace detail",
            "workflow_detail",
            "Grounded workflow detail",
            "Best when the image should support a paragraph as a quiet contextual detail rather than a hero image.",
            (
                "Create a grounded editorial workspace image that supports this article section. "
                f"Context to interpret: {subject}. "
                f"{evidence_sentence}"
                "Use subtle objects, planning materials, and visual hierarchy to imply analysis and decision-making. "
                f"Composition: {aspect_ratio}. "
                "No readable text, no brand marks, no screenshots, no copied paragraph content."
            ),
        ),
    ]
    return [
        _localize_prompt_candidate(
            {
                "id": prompt_id,
                "label": label,
                "direction_type": direction_type,
                "visual_strategy": visual_strategy,
                "reason": reason,
                "prompt": _normalize_text(prompt, limit=1200),
                "source": "cloud_visual_brief",
                "evidence_refs": _site_context_evidence_refs(
                    _dict(options.get("site_knowledge_context"))
                ),
                "requires_operator_review": True,
                "write_posture": "candidate_only",
                "direct_wordpress_write": False,
            },
            locale=str(options.get("locale") or ""),
        )
        for prompt_id, label, direction_type, visual_strategy, reason, prompt in prompts
    ]


def _build_batch_generation_plan(options: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": "local_reviewed_batch_plan",
        "status": "available_with_local_orchestration",
        "owner": "local_plugin_control_plane",
        "requires_entitlement": True,
        "requires_user_review": True,
        "requires_per_item_prompt_review": True,
        "default_item_count": 1,
        "max_items_per_user_action": min(10, max(1, int(options.get("per_page") or 1))),
        "recommended_execution_pattern": "inline",
        "future_execution_pattern": "whole_run_offload",
        "queue_owner": "cloud_runtime_worker",
        "quota_owner": "cloud_runtime_entitlement",
        "result_owner": "cloud_runtime_result",
        "write_owner": "local_wordpress_approval_flow",
        "direct_wordpress_write": False,
        "do_not_autorun": True,
        "failure_policy": {
            "partial_results_allowed": True,
            "failed_items_require_user_retry": True,
        },
    }


def _build_prompt_prefill_plan(options: dict[str, Any]) -> dict[str, Any]:
    orientation = str(options.get("orientation") or "").strip().lower()
    purpose = str(options.get("purpose") or "image_reference_candidate").strip()
    return {
        "mode": "local_context_prefill",
        "owner": "local_plugin_ui",
        "requires_user_review": True,
        "max_prompt_chars": 1200,
        "source_priority": [
            "user_edited_prompt",
            "image_source_runtime_input.query",
            "post_title",
            "post_excerpt",
            "selected_text_context",
        ],
        "local_prompt_fields": [
            {
                "field": "subject",
                "required": True,
                "sources": ["user_edited_prompt", "image_source_runtime_input.query"],
                "max_chars": 220,
            },
            {
                "field": "context",
                "required": False,
                "sources": ["post_title", "post_excerpt", "selected_text_context"],
                "max_chars": 420,
            },
            {
                "field": "composition",
                "required": False,
                "default": _composition_hint(orientation),
                "max_chars": 180,
            },
            {
                "field": "style",
                "required": False,
                "default": _style_hint(purpose),
                "max_chars": 180,
            },
            {
                "field": "constraints",
                "required": False,
                "default": (
                    "No text overlays, no logos, no direct trademark use unless "
                    "supplied by the user."
                ),
                "max_chars": 180,
            },
        ],
        "assembly": {
            "format": "plain_text_sections",
            "section_order": ["subject", "context", "composition", "style", "constraints"],
            "joiner": ". ",
        },
        "safety": {
            "must_review_before_execute": True,
            "do_not_autorun": True,
            "do_not_include_secrets": True,
            "do_not_include_wordpress_credentials": True,
            "direct_wordpress_write": False,
        },
    }


def _composition_hint(orientation: str) -> str:
    normalized = str(orientation or "").strip().lower()
    if normalized == "portrait":
        return "Portrait composition, clear central subject, editorial crop."
    if normalized in {"square", "squarish"}:
        return "Square composition, balanced subject placement, clean margins."
    return "Wide editorial hero composition, clear focal point, usable negative space."


def _style_hint(purpose: str) -> str:
    normalized = str(purpose or "").strip().lower()
    if "product" in normalized:
        return "Professional product photography, natural lighting, realistic materials."
    if "featured" in normalized or "hero" in normalized:
        return "Editorial hero image, polished but realistic, publication-ready."
    return "Realistic editorial image, natural lighting, high visual clarity."


def _default_generation_aspect_ratio(orientation: str) -> str:
    normalized = str(orientation or "").strip().lower()
    if normalized == "portrait":
        return "3:4"
    if normalized in {"square", "squarish"}:
        return "1:1"
    return "16:9"


def _normalize_text(value: Any, *, limit: int) -> str:
    text = str(value or "").strip()
    text = " ".join(text.split())
    return text[:limit]


def _normalize_token(value: Any, *, limit: int) -> str:
    return "".join(
        ch for ch in str(value or "").strip().lower()[:limit] if ch.isalnum() or ch in {"_", "-"}
    )


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_locale(value: Any) -> str:
    normalized = str(value or "").strip().replace("-", "_")
    if normalized.lower() == "zh_cn":
        return "zh_CN"
    return _normalize_token(normalized, limit=20)


def _is_zh_cn_locale(value: Any) -> bool:
    return str(value or "").strip().replace("-", "_").lower() == "zh_cn"


def _normalize_visual_context(value: Any) -> dict[str, Any]:
    source = _dict(value)
    if not source:
        return {}
    allowed_text_fields = {
        "title": 160,
        "excerpt": 240,
        "content_summary": 420,
        "selected_text": MAX_VISUAL_CONTEXT_CHARS,
        "selected_block_text": MAX_VISUAL_CONTEXT_CHARS,
        "manual_query": 160,
        "fallback_query": 160,
    }
    context: dict[str, Any] = {}
    for field, limit in allowed_text_fields.items():
        text = _normalize_text(source.get(field), limit=limit)
        if text:
            context[field] = text
    image_mode = _normalize_token(source.get("image_mode") or source.get("image_use"), limit=40)
    if image_mode:
        context["image_mode"] = image_mode
    post_id = _coerce_int(source.get("post_id"), default=0)
    if post_id > 0:
        context["post_id"] = post_id
    selected_block_name = _normalize_token(source.get("selected_block_name"), limit=80)
    if selected_block_name:
        context["selected_block_name"] = selected_block_name
    context["avoid_brand_logos"] = bool(source.get("avoid_brand_logos"))
    query_intent = _dict(source.get("query_intent"))
    if query_intent:
        context["query_intent"] = {
            "rewrite_abstract_terms": bool(query_intent.get("rewrite_abstract_terms")),
            "prefer_concrete_visual_scene": bool(query_intent.get("prefer_concrete_visual_scene")),
            "return_alternate_queries": bool(query_intent.get("return_alternate_queries")),
        }
    return context


def _normalize_site_knowledge_context(value: Any) -> dict[str, Any]:
    source = _dict(value)
    if not source:
        return {}
    results = []
    for item in _list(source.get("results"))[:4]:
        result = _dict(item)
        if not result:
            continue
        results.append(
            {
                "post_id": _coerce_int(result.get("post_id"), default=0),
                "source_type": _normalize_token(result.get("source_type"), limit=32),
                "title": _normalize_text(result.get("title"), limit=160),
                "url": _normalize_url(result.get("url")),
                "score": round(max(0.0, min(1.0, _coerce_float(result.get("score")))), 4),
                "match_context": _normalize_text(
                    result.get("match_context") or result.get("chunk_text"),
                    limit=320,
                ),
            }
        )
    return {
        "status": _normalize_token(source.get("status"), limit=40) or "unavailable",
        "intent": _normalize_token(source.get("intent"), limit=40) or "image_context",
        "evidence_gate": _dict(source.get("evidence_gate")),
        "rerank": _dict(source.get("rerank")),
        "results": results,
    }


def _normalize_llm_prompt_plan(value: Any) -> dict[str, Any]:
    source = _dict(value)
    if not source:
        return {}
    candidates = []
    for index, item in enumerate(_list(source.get("prompt_candidates"))[:3], start=1):
        candidate = _dict(item)
        prompt = _normalize_text(candidate.get("prompt"), limit=1200)
        if not prompt:
            continue
        candidates.append(
            {
                "id": _normalize_token(candidate.get("id"), limit=80) or f"llm_prompt_{index}",
                "label": _normalize_text(candidate.get("label"), limit=80) or f"LLM prompt {index}",
                "prompt": prompt,
                "direction_type": _normalize_token(
                    candidate.get("direction_type"),
                    limit=80,
                ),
                "visual_strategy": _normalize_text(
                    candidate.get("visual_strategy"),
                    limit=160,
                ),
                "reason": _normalize_text(candidate.get("reason"), limit=220),
                "image_use": _normalize_token(candidate.get("image_use"), limit=80),
            }
        )
    return {
        "status": _normalize_token(source.get("status"), limit=40) or "unavailable",
        "profile_id": _normalize_text(source.get("profile_id"), limit=120),
        "provider_id": _normalize_text(source.get("provider_id"), limit=120),
        "model_id": _normalize_text(source.get("model_id"), limit=160),
        "fallback": _normalize_text(source.get("fallback"), limit=160),
        "prompt_candidates": candidates,
    }


_ZH_DIRECTION_DISPLAY: dict[str, tuple[str, str, str]] = {
    "workspace_detail": (
        "工作区细节",
        "用工作区中的具体物件承载文章主题。",
        "适合用安静、真实的细节辅助段落理解。",
    ),
    "workflow_detail": (
        "流程细节",
        "呈现分析、规划或执行流程中的关键细节。",
        "适合把段落内容转成可理解的操作过程。",
    ),
    "hero_editorial": (
        "特色图方向",
        "用自然的编辑场景概括文章重点。",
        "适合需要一张可作为特色图的文章配图。",
    ),
    "editorial_scene": (
        "特色图方向",
        "用自然的编辑场景概括文章重点。",
        "适合需要一张可作为特色图的文章配图。",
    ),
    "article_cover": (
        "特色图方向",
        "用自然的编辑场景概括文章重点。",
        "适合需要一张可作为特色图的文章配图。",
    ),
    "concept_metaphor": (
        "概念隐喻",
        "用物件、空间关系和人物状态表达抽象概念。",
        "适合把抽象策略或方法论转成可视化画面。",
    ),
    "conceptual_metaphor": (
        "概念隐喻",
        "用物件、空间关系和人物状态表达抽象概念。",
        "适合把抽象策略或方法论转成可视化画面。",
    ),
    "product_context": (
        "产品场景",
        "把产品或服务放进真实使用场景中呈现。",
        "适合展示产品价值、使用环境或服务触点。",
    ),
}


def _localize_prompt_candidate(candidate: dict[str, Any], *, locale: str) -> dict[str, Any]:
    if not _is_zh_cn_locale(locale):
        return candidate
    direction_type = _normalize_token(candidate.get("direction_type"), limit=80)
    display = _ZH_DIRECTION_DISPLAY.get(direction_type) or (
        "配图方向",
        "围绕文章上下文生成可审核的配图方案。",
        "适合作为人工审核前的备选配图方向。",
    )
    candidate["localized_label"] = display[0]
    candidate["localized_strategy"] = display[1]
    candidate["localized_reason"] = display[2]
    return candidate


def _prompt_candidates_from_llm_plan(
    llm_prompt_plan: dict[str, Any],
    *,
    evidence_refs: list[dict[str, Any]],
    locale: str,
) -> list[dict[str, Any]]:
    if str(llm_prompt_plan.get("status") or "") != "ready":
        return []
    candidates = []
    for item in _list(llm_prompt_plan.get("prompt_candidates"))[:3]:
        candidate = _dict(item)
        prompt = _normalize_text(candidate.get("prompt"), limit=1200)
        if not prompt:
            continue
        candidates.append(
            _localize_prompt_candidate(
                {
                    "id": _normalize_token(candidate.get("id"), limit=80)
                    or _hash_text(prompt)[:12],
                    "label": _normalize_text(candidate.get("label"), limit=80)
                    or "LLM visual prompt",
                    "prompt": prompt,
                    "direction_type": _normalize_token(
                        candidate.get("direction_type"),
                        limit=80,
                    ),
                    "visual_strategy": _normalize_text(
                        candidate.get("visual_strategy"),
                        limit=160,
                    ),
                    "reason": _normalize_text(candidate.get("reason"), limit=220),
                    "image_use": _normalize_token(candidate.get("image_use"), limit=80),
                    "source": "cloud_llm_prompt_planner",
                    "planner_profile_id": str(llm_prompt_plan.get("profile_id") or ""),
                    "planner_model_id": str(llm_prompt_plan.get("model_id") or ""),
                    "evidence_refs": evidence_refs,
                    "requires_operator_review": True,
                    "write_posture": "candidate_only",
                    "direct_wordpress_write": False,
                },
                locale=locale,
            )
        )
    return candidates


def _site_context_evidence_refs(site_context: dict[str, Any]) -> list[dict[str, Any]]:
    refs = []
    for item in _list(site_context.get("results"))[:4]:
        result = _dict(item)
        title = _normalize_text(result.get("title"), limit=120)
        if not title and not result.get("url"):
            continue
        refs.append(
            {
                "post_id": _coerce_int(result.get("post_id"), default=0),
                "source_type": _normalize_token(result.get("source_type"), limit=32),
                "title": title,
                "url": _normalize_url(result.get("url")),
                "score": round(max(0.0, min(1.0, _coerce_float(result.get("score")))), 4),
            }
        )
    return refs


def _site_context_prompt_evidence(site_context: dict[str, Any]) -> str:
    snippets = []
    for item in _list(site_context.get("results"))[:2]:
        result = _dict(item)
        title = _normalize_text(result.get("title"), limit=100)
        context = _normalize_text(result.get("match_context"), limit=180)
        if title and context:
            snippets.append(f"{title}: {context}")
        elif title:
            snippets.append(title)
        elif context:
            snippets.append(context)
    return " | ".join(snippets)[:420]


def _visual_query_from_context(value: Any) -> str:
    text = _normalize_text(value, limit=MAX_VISUAL_CONTEXT_CHARS)
    if not text:
        return "editorial article illustration"
    lower = text.lower()
    term_map = (
        ("seo", "search strategy workspace"),
        ("aeo", "answer engine experience planning"),
        ("geo", "generative search visibility analysis"),
        ("ai", "artificial intelligence editorial planning"),
        ("wordpress", "wordpress publishing workflow"),
        ("content", "content strategy desk"),
        ("上下文", "editorial context mapping"),
        ("文章", "article planning workspace"),
        ("段落", "section-level editorial concept"),
        ("读者", "reader journey research"),
        ("搜索", "search discovery analysis"),
        ("答案", "answer-focused content planning"),
    )
    terms = [visual for needle, visual in term_map if needle in lower]
    if terms:
        return _normalize_text(" ".join(_dedupe_texts(terms, limit=5)), limit=180)
    return _normalize_text(text, limit=180)


def _dedupe_texts(values: list[str], *, limit: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = _normalize_text(value, limit=220)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _normalize_url(value: Any) -> str:
    url = str(value or "").strip()
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return url


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _suggested_candidate_filename(
    *,
    provider: str,
    stable_id: str,
    download_url: str,
    source_url: str,
) -> str:
    provider_slug = _filename_slug(provider, fallback="image")
    identity = _hash_text(stable_id or download_url or source_url)[:12]
    extension = _safe_image_extension(download_url) or _safe_image_extension(source_url) or "jpg"
    return f"{provider_slug}-image-{identity}.{extension}"


def _filename_slug(value: str, *, fallback: str) -> str:
    slug = []
    for ch in value.strip().lower():
        if ch.isalnum():
            slug.append(ch)
        elif ch in {"-", "_", "."}:
            slug.append("-")
    normalized = "-".join(part for part in "".join(slug).split("-") if part)
    return normalized[:80] or fallback


def _safe_image_extension(url: str) -> str:
    path = unquote(urlsplit(url).path or "")
    extension = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    if extension == "jpeg":
        return "jpg"
    return extension if extension in {"jpg", "png", "webp", "avif"} else ""


def _attribution(*, provider: str, photographer: str, source_url: str) -> str:
    creator = photographer or "Unknown creator"
    suffix = f" {source_url}" if source_url else ""
    return f"{provider} image by {creator}.{suffix}".strip()


def _map_http_error(response: httpx.Response) -> str:
    status = response.status_code
    if status in {401, 403}:
        return "provider.auth_error"
    if status == 429:
        return "provider.rate_limited"
    if status >= 500:
        return "provider.upstream_error"
    return "provider.http_error"


def _extract_http_error_message(response: httpx.Response) -> str:
    if _response_too_large(response, max_bytes=MAX_PROVIDER_RESPONSE_BYTES):
        return f"Image source provider request failed with HTTP {response.status_code}"
    try:
        data = response.json()
    except ValueError:
        data = {}
    if isinstance(data, dict):
        message = data.get("message") or data.get("error") or data.get("errors")
        if isinstance(message, list):
            return _normalize_text("; ".join(str(item) for item in message), limit=200)
        if message:
            return _normalize_text(message, limit=200)
    return f"Image source provider request failed with HTTP {response.status_code}"


def _response_too_large(response: httpx.Response, *, max_bytes: int) -> bool:
    content_length = response.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                return True
        except ValueError:
            pass
    return len(response.content) > max_bytes
