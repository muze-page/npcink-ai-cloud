from __future__ import annotations

import base64
import binascii
import math
import re
import time
from collections.abc import Iterable
from dataclasses import replace
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.adapters.providers.base import (
    IMAGE_GENERATION_PROVIDER_ERROR_MESSAGE,
    VISION_PROVIDER_ERROR_MESSAGE,
    CatalogInstanceSeed,
    CatalogModelSeed,
    ProviderCatalogSnapshot,
    ProviderExecutionError,
    ProviderExecutionRequest,
    ProviderExecutionResult,
    ProviderMediaCandidate,
)
from app.domain.hosted_model_defaults import GROK_IMAGINE_IMAGE_MODEL_ID

DEEPSEEK_MODEL_PRICING_PER_MILLION: dict[str, dict[str, float]] = {
    "deepseek-v4-flash": {
        "input_cache_hit": 0.0028,
        "input_cache_miss": 0.14,
        "output": 0.28,
    },
    "deepseek-chat": {
        "input_cache_hit": 0.0028,
        "input_cache_miss": 0.14,
        "output": 0.28,
    },
    "deepseek-reasoner": {
        "input_cache_hit": 0.0028,
        "input_cache_miss": 0.14,
        "output": 0.28,
    },
    "deepseek-v4-pro": {
        "input_cache_hit": 0.003625,
        "input_cache_miss": 0.435,
        "output": 0.87,
    },
}
MAX_UPSTREAM_ERROR_MESSAGE_CHARS = 4000
MAX_REQUEST_METADATA_ENTRIES = 16
MAX_REQUEST_METADATA_KEY_CHARS = 64
MAX_REQUEST_METADATA_VALUE_CHARS = 512
MAX_PROVIDER_IMAGE_COUNT = 4
MAX_PROVIDER_IMAGE_BYTES = 24 * 1024 * 1024
MAX_PROVIDER_IMAGE_TOTAL_BYTES = 64 * 1024 * 1024
MAX_PROVIDER_IMAGE_BASE64_CHARS = ((MAX_PROVIDER_IMAGE_BYTES + 2) // 3) * 4
MAX_PROVIDER_IMAGE_RESPONSE_BYTES = (((MAX_PROVIDER_IMAGE_TOTAL_BYTES + 2) // 3) * 4) + (
    1024 * 1024
)
ALLOWED_PROVIDER_IMAGE_RESPONSE_FORMATS = frozenset({"url", "b64_json"})
ALLOWED_REASONING_EFFORTS = frozenset({"none", "low", "medium", "high", "max"})
ALLOWED_PROVIDER_IMAGE_USAGE_FIELDS = frozenset(
    {
        "cost",
        "cost_in_usd",
        "cost_in_usd_ticks",
        "image_count",
        "input_tokens",
        "output_tokens",
        "prompt_tokens",
        "total_tokens",
    }
)
SAMPLE_IMAGE_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c02"
    "0000000b4944415478da6364f80f00010501012718e3660000000049454e44ae426082"
)


def _truncate_upstream_error_message(value: str) -> str:
    if len(value) <= MAX_UPSTREAM_ERROR_MESSAGE_CHARS:
        return value
    return f"{value[:MAX_UPSTREAM_ERROR_MESSAGE_CHARS]}...[truncated]"


class OpenAIProviderAdapter:
    provider_id = "openai"
    display_name = "OpenAI Compatible"
    adapter_type = "openai"

    def __init__(
        self,
        *,
        base_url: str = "https://api.openai.com/v1",
        api_key: str | None = None,
        organization: str | None = None,
        timeout_seconds: float = 30.0,
        sample_catalog_profile: str = "",
        app_name: str = "npcink-ai-cloud",
        allow_http_without_api_key: bool = False,
        allow_sample_catalog: bool = True,
        allow_sample_execution: bool = True,
        extra_headers: dict[str, str] | None = None,
        model_namespace_prefix: str = "",
        provider_label: str = "",
        image_output_hosts: Iterable[str] = (),
        image_response_format: str | None = None,
        default_reasoning_effort: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.organization = organization
        self.timeout_seconds = timeout_seconds
        self.sample_catalog_profile = str(sample_catalog_profile or "").strip().lower()
        self.app_name = app_name
        self.allow_http_without_api_key = allow_http_without_api_key
        self.allow_sample_catalog = allow_sample_catalog
        self.allow_sample_execution = allow_sample_execution
        self.extra_headers = {
            str(key).strip(): str(value).strip()
            for key, value in (extra_headers or {}).items()
            if str(key).strip() and str(value).strip()
        }
        self.model_namespace_prefix = str(model_namespace_prefix or "").strip().strip("/")
        self.provider_label = str(provider_label or "").strip()
        self.image_output_hosts = self._normalize_image_output_hosts(image_output_hosts)
        normalized_image_response_format = str(image_response_format or "").strip().lower()
        if (
            normalized_image_response_format
            and normalized_image_response_format not in ALLOWED_PROVIDER_IMAGE_RESPONSE_FORMATS
        ):
            raise ValueError("image_response_format must be url or b64_json")
        self.image_response_format = normalized_image_response_format or None
        normalized_reasoning_effort = str(default_reasoning_effort or "").strip().lower()
        if (
            normalized_reasoning_effort
            and normalized_reasoning_effort not in ALLOWED_REASONING_EFFORTS
        ):
            raise ValueError(
                "default_reasoning_effort must be none, low, medium, high, or max"
            )
        self.default_reasoning_effort = normalized_reasoning_effort or None
        if self.provider_label:
            self.display_name = self.provider_label
        self.transport = transport

    def fetch_catalog(self) -> ProviderCatalogSnapshot:
        if self._http_enabled:
            return self._fetch_http_catalog()
        if not self.allow_sample_catalog:
            raise RuntimeError("provider catalog refresh requires configured upstream credentials")

        return self._build_sample_catalog()

    def _build_sample_catalog(self) -> ProviderCatalogSnapshot:
        models = [
            CatalogModelSeed(
                model_id="gpt-4.1-mini",
                family="gpt-4.1",
                feature="text",
                status="available",
                context_window=128000,
                price_input=0.4,
                price_output=1.6,
                fallback_candidate=True,
                raw_json={"tier": "balanced"},
                instances=[
                    CatalogInstanceSeed(
                        instance_id="openai-us-east-text-economy",
                        endpoint_variant="chat_completions",
                        region="us-east",
                        capability_tags=["text", "economy"],
                        is_default=False,
                        weight=80,
                    ),
                    CatalogInstanceSeed(
                        instance_id="openai-us-east-text-balanced",
                        endpoint_variant="chat_completions",
                        region="us-east",
                        capability_tags=["text", "balanced"],
                        is_default=True,
                        weight=100,
                    ),
                    CatalogInstanceSeed(
                        instance_id="openai-us-east-text-quality",
                        endpoint_variant="responses",
                        region="us-east",
                        capability_tags=["text", "quality"],
                        is_default=False,
                        weight=120,
                    ),
                ],
            ),
            CatalogModelSeed(
                model_id="gpt-4.1",
                family="gpt-4.1",
                feature="vision",
                status="available",
                context_window=128000,
                price_input=2.0,
                price_output=8.0,
                fallback_candidate=False,
                raw_json={"tier": "quality"},
                instances=[
                    CatalogInstanceSeed(
                        instance_id="openai-us-east-vision-default",
                        endpoint_variant="responses",
                        region="us-east",
                        capability_tags=["vision", "default", "quality"],
                        is_default=True,
                        weight=100,
                    )
                ],
            ),
            CatalogModelSeed(
                model_id="text-embedding-3-small",
                family="text-embedding-3",
                feature="embedding",
                status="available",
                context_window=8192,
                price_input=0.02,
                price_output=0.0,
                fallback_candidate=False,
                raw_json={"tier": "embedding"},
                instances=[
                    CatalogInstanceSeed(
                        instance_id="openai-us-east-embed-default",
                        endpoint_variant="embeddings",
                        region="us-east",
                        capability_tags=["embedding", "default"],
                        is_default=True,
                        weight=100,
                    )
                ],
            ),
            CatalogModelSeed(
                model_id=GROK_IMAGINE_IMAGE_MODEL_ID,
                family="z-image",
                feature="image_generation",
                status="available",
                context_window=None,
                price_input=None,
                price_output=None,
                fallback_candidate=False,
                raw_json={
                    "tier": "quality",
                    "surface": "image_generation",
                },
                instances=[
                    CatalogInstanceSeed(
                        instance_id=f"openai-global-{self._slugify(GROK_IMAGINE_IMAGE_MODEL_ID)}",
                        endpoint_variant="image_generations",
                        region="global",
                        capability_tags=[
                            "image_generation",
                            "default",
                            "quality",
                            "z-image",
                        ],
                        is_default=True,
                        weight=120,
                    )
                ],
            ),
        ]

        if self.sample_catalog_profile == "free-gpt55":
            models.insert(
                0,
                CatalogModelSeed(
                    model_id="gpt-5.5",
                    family="gpt-5.5",
                    feature="text",
                    status="available",
                    context_window=256000,
                    price_input=0.0,
                    price_output=0.0,
                    fallback_candidate=True,
                    raw_json={
                        "tier": "quality",
                        "commercial_tier": "free",
                        "surface": "free_gpt55_tools",
                    },
                    instances=[
                        CatalogInstanceSeed(
                            instance_id="openai-global-free-gpt55",
                            endpoint_variant="responses",
                            region="global",
                            capability_tags=[
                                "text",
                                "quality",
                                "free-gpt55",
                                "hosted-free",
                            ],
                            is_default=True,
                            weight=140,
                        )
                    ],
                ),
            )

        return ProviderCatalogSnapshot(
            provider_id=self.provider_id,
            display_name=self.display_name,
            adapter_type=self.adapter_type,
            models=models,
        )

    def _fetch_http_catalog(self) -> ProviderCatalogSnapshot:
        try:
            with self._build_catalog_client() as client:
                response = client.get("/models")
                response.raise_for_status()
        except httpx.TimeoutException as error:
            raise RuntimeError("provider catalog refresh timed out") from error
        except httpx.HTTPStatusError as error:
            message = self._extract_http_error_message(error.response)
            raise RuntimeError(
                f"provider catalog refresh failed with {error.response.status_code}: {message}"
            ) from error
        except httpx.RequestError as error:
            raise RuntimeError(f"provider catalog refresh network error: {error}") from error

        response_json = response.json()
        raw_models = response_json.get("data")
        if not isinstance(raw_models, list):
            raise ValueError("provider catalog response missing data list")

        catalog_models: list[CatalogModelSeed] = []
        for raw_model in raw_models:
            model_seed = self._build_catalog_model_seed(raw_model)
            if model_seed is None:
                continue
            catalog_models.append(model_seed)

        if not catalog_models:
            raise ValueError("provider catalog refresh returned no usable models")

        catalog_models.sort(key=self._catalog_sort_key)

        return ProviderCatalogSnapshot(
            provider_id=self.provider_id,
            display_name=self.display_name,
            adapter_type=self.adapter_type,
            models=catalog_models,
        )

    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        self._maybe_raise_simulated_error(request)
        if not self._http_enabled:
            if not self.allow_sample_execution:
                raise ProviderExecutionError(
                    "provider.auth_invalid",
                    "provider execution requires configured upstream credentials",
                )
            return self._execute_sample(request)

        return self._execute_http(request)

    @property
    def _http_enabled(self) -> bool:
        return bool(self.api_key) or self.allow_http_without_api_key

    def _build_http_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": self.app_name,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.organization:
            headers["OpenAI-Organization"] = self.organization
        headers.update(self.extra_headers)
        return headers

    def _build_catalog_client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            headers=self._build_http_headers(),
            timeout=max(self.timeout_seconds, 0.001),
            transport=self.transport,
        )

    def _execute_http(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        endpoint_path, payload = self._build_http_request(request)
        result_request = request
        started_at = time.monotonic()

        try:
            with self._build_client(request.timeout_ms) as client:
                response = self._post_with_compatibility_retry(client, endpoint_path, payload)
                if (
                    response.status_code == 404
                    and endpoint_path == "/responses"
                    and self._can_retry_responses_as_chat_completions(request)
                ):
                    result_request = replace(request, endpoint_variant="chat_completions")
                    endpoint_path, payload = self._build_http_request(result_request)
                    response = self._post_with_compatibility_retry(client, endpoint_path, payload)
                response.raise_for_status()
        except httpx.TimeoutException as error:
            raise ProviderExecutionError(
                "provider.timeout",
                f"provider call exceeded timeout budget for {request.instance_id}",
            ) from error
        except httpx.HTTPStatusError as error:
            error_code = self._map_http_status_error(error.response.status_code)
            error_message = (
                IMAGE_GENERATION_PROVIDER_ERROR_MESSAGE
                if result_request.endpoint_variant == "image_generations"
                else (
                    VISION_PROVIDER_ERROR_MESSAGE
                    if result_request.execution_kind == "vision"
                    else self._extract_http_error_message(error.response)
                )
            )
            raise ProviderExecutionError(
                error_code,
                error_message,
                retryable=error.response.status_code >= 500 or error.response.status_code == 429,
            ) from error
        except httpx.RequestError as error:
            raise ProviderExecutionError(
                "provider.network_error",
                str(error),
            ) from error

        try:
            response_json = response.json()
        except ValueError as error:
            if result_request.endpoint_variant == "image_generations":
                raise ProviderExecutionError(
                    "provider.output_contract_invalid",
                    "image generation response must be a JSON object",
                ) from error
            raise
        if result_request.endpoint_variant == "image_generations" and not isinstance(
            response_json,
            dict,
        ):
            raise ProviderExecutionError(
                "provider.output_contract_invalid",
                "image generation response must be a JSON object",
            )
        latency_ms = max(1, int((time.monotonic() - started_at) * 1000))
        return self._build_http_result(result_request, response_json, latency_ms)

    def _post_with_compatibility_retry(
        self,
        client: httpx.Client,
        endpoint_path: str,
        payload: dict[str, Any],
    ) -> httpx.Response:
        response = self._post_provider_request(client, endpoint_path, payload)
        if (
            response.status_code == 400
            and "metadata" in payload
            and self._response_reports_unsupported_parameter(response, "metadata")
        ):
            retry_payload = dict(payload)
            retry_payload.pop("metadata", None)
            response = self._post_provider_request(client, endpoint_path, retry_payload)
            payload = retry_payload
        if (
            response.status_code == 400
            and payload.get("temperature") != 1
            and self._response_requires_temperature_one(response)
        ):
            retry_payload = dict(payload)
            retry_payload["temperature"] = 1
            response = self._post_provider_request(client, endpoint_path, retry_payload)
        return response

    def _post_provider_request(
        self,
        client: httpx.Client,
        endpoint_path: str,
        payload: dict[str, Any],
    ) -> httpx.Response:
        if endpoint_path != "/images/generations":
            return client.post(endpoint_path, json=payload)

        with client.stream(
            "POST",
            endpoint_path,
            json=payload,
            headers={"Accept-Encoding": "identity"},
        ) as streamed_response:
            content_length = streamed_response.headers.get("content-length")
            if content_length is not None:
                try:
                    declared_length = int(content_length)
                except ValueError:
                    declared_length = 0
                if declared_length > MAX_PROVIDER_IMAGE_RESPONSE_BYTES:
                    raise ProviderExecutionError(
                        "provider.output_contract_invalid",
                        "image generation response exceeds the encoded response byte limit",
                    )

            response_content = bytearray()
            for chunk in streamed_response.iter_bytes():
                response_content.extend(chunk)
                if len(response_content) > MAX_PROVIDER_IMAGE_RESPONSE_BYTES:
                    raise ProviderExecutionError(
                        "provider.output_contract_invalid",
                        "image generation response exceeds the encoded response byte limit",
                    )
            return httpx.Response(
                status_code=streamed_response.status_code,
                headers=streamed_response.headers,
                content=bytes(response_content),
                request=streamed_response.request,
                extensions=streamed_response.extensions,
            )

    def _can_retry_responses_as_chat_completions(
        self,
        request: ProviderExecutionRequest,
    ) -> bool:
        if request.endpoint_variant != "responses":
            return False
        options = self._resolve_request_options(request.input_payload)
        messages = options.get("messages")
        return isinstance(messages, list) and bool(messages)

    @staticmethod
    def _response_reports_unsupported_parameter(
        response: httpx.Response,
        parameter: str,
    ) -> bool:
        try:
            payload = response.json()
        except ValueError:
            return False
        error_payload = payload.get("error") if isinstance(payload, dict) else None
        values: list[object] = [error_payload]
        if isinstance(error_payload, dict):
            values.extend(
                [
                    error_payload.get("message"),
                    error_payload.get("param"),
                    error_payload.get("code"),
                    error_payload.get("type"),
                ]
            )
        values.append(payload)
        needle = parameter.lower()
        return any(
            needle in str(value).lower() and "unsupported" in str(value).lower()
            for value in values
        )

    @staticmethod
    def _response_requires_temperature_one(response: httpx.Response) -> bool:
        try:
            payload = response.json()
        except ValueError:
            return False
        error_payload = payload.get("error") if isinstance(payload, dict) else None
        message = (
            error_payload.get("message")
            if isinstance(error_payload, dict)
            else error_payload
        )
        normalized = str(message or "").strip().lower()
        return "temperature" in normalized and "only 1 is allowed" in normalized

    def _build_client(self, request_timeout_ms: int) -> httpx.Client:
        timeout_seconds = min(
            max(request_timeout_ms / 1000, 0.001),
            max(self.timeout_seconds, 0.001),
        )

        return httpx.Client(
            base_url=self.base_url,
            headers=self._build_http_headers(),
            timeout=timeout_seconds,
            transport=self.transport,
        )

    def _build_http_request(
        self,
        request: ProviderExecutionRequest,
    ) -> tuple[str, dict[str, Any]]:
        options = self._resolve_request_options(request.input_payload)
        runtime_model_id = self._resolve_runtime_model_id(request.model_id)
        if request.endpoint_variant == "embeddings":
            embedding_payload: dict[str, Any] = {
                "model": runtime_model_id,
                "input": self._resolve_embedding_input(options),
            }
            if isinstance(options.get("encoding_format"), str):
                embedding_payload["encoding_format"] = options["encoding_format"]
            return "/embeddings", embedding_payload

        if request.endpoint_variant == "image_generations":
            image_payload: dict[str, Any] = {
                "model": runtime_model_id,
                "prompt": self._resolve_image_generation_prompt(options),
            }
            self._apply_image_generation_request_options(image_payload, options)
            return "/images/generations", image_payload

        if request.endpoint_variant == "responses":
            responses_payload: dict[str, Any] = {
                "model": runtime_model_id,
                "input": self._resolve_responses_input(options),
            }
            if isinstance(options.get("temperature"), (int, float)):
                responses_payload["temperature"] = options["temperature"]
            if isinstance(options.get("max_output_tokens"), int):
                responses_payload["max_output_tokens"] = options["max_output_tokens"]
            self._apply_responses_request_options(responses_payload, options)
            return "/responses", responses_payload

        chat_payload: dict[str, Any] = {
            "model": runtime_model_id,
            "messages": self._resolve_chat_messages(options),
        }
        if isinstance(options.get("temperature"), (int, float)):
            chat_payload["temperature"] = options["temperature"]
        if isinstance(options.get("max_tokens"), int):
            chat_payload["max_tokens"] = options["max_tokens"]
        self._apply_chat_request_options(chat_payload, options)
        return "/chat/completions", chat_payload

    def _build_http_result(
        self,
        request: ProviderExecutionRequest,
        response_json: dict[str, Any],
        latency_ms: int,
    ) -> ProviderExecutionResult:
        if request.endpoint_variant == "embeddings":
            data = response_json.get("data")
            first_embedding = data[0] if isinstance(data, list) and data else {}
            embedding = (
                first_embedding.get("embedding") if isinstance(first_embedding, dict) else []
            )
            usage = response_json.get("usage", {})
            tokens_in = self._coerce_int(usage.get("prompt_tokens"))
            tokens_out = 0
            output = {
                "embedding": embedding if isinstance(embedding, list) else [],
                "dimensions": len(embedding) if isinstance(embedding, list) else 0,
                "model_id": response_json.get("model", request.model_id),
                "usage": usage if isinstance(usage, dict) else {},
            }
            return ProviderExecutionResult(
                output=output,
                latency_ms=latency_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost=self._estimate_cost(request, tokens_in, tokens_out, usage=usage),
            )

        if request.endpoint_variant == "image_generations":
            usage = response_json.get("usage", {})
            tokens_in = (
                self._coerce_int(usage.get("prompt_tokens")) if isinstance(usage, dict) else 0
            )
            cost = self._extract_image_generation_cost(usage)
            usage_for_cost = usage if isinstance(usage, dict) else {}
            resolved_cost = (
                cost
                if cost > 0
                else self._estimate_cost(request, tokens_in, 0, usage=usage_for_cost)
            )
            try:
                media_candidates = self._build_image_media_candidates(response_json)
            except ProviderExecutionError as error:
                raise ProviderExecutionError(
                    error.error_code,
                    error.message,
                    retryable=error.retryable,
                    tokens_in=tokens_in,
                    cost=resolved_cost,
                ) from error
            output = {
                "model_id": self._optional_string(response_json.get("model")) or request.model_id,
                "candidate_count": len(media_candidates),
                "usage": self._sanitize_image_generation_usage(usage),
            }
            return ProviderExecutionResult(
                output=output,
                latency_ms=latency_ms,
                tokens_in=tokens_in,
                tokens_out=0,
                cost=resolved_cost,
                media_candidates=media_candidates,
            )

        if request.endpoint_variant == "responses":
            usage = response_json.get("usage", {})
            output_text = self._extract_responses_output_text(response_json)
            response_output = response_json.get("output")
            output = {
                "output_text": output_text,
                "messages": [{"role": "assistant", "content": output_text}],
                "model_id": response_json.get("model", request.model_id),
                "usage": usage if isinstance(usage, dict) else {},
            }
            if isinstance(response_output, list):
                output["output"] = response_output
                tool_calls = self._extract_responses_tool_calls(response_output)
                if tool_calls:
                    output["tool_calls"] = tool_calls
                    output["messages"] = [
                        {
                            "role": "assistant",
                            "content": output_text,
                            "tool_calls": tool_calls,
                        }
                    ]
            tokens_in = self._coerce_int(usage.get("input_tokens"))
            tokens_out = self._coerce_int(usage.get("output_tokens"))
            return ProviderExecutionResult(
                output=output,
                latency_ms=latency_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost=self._estimate_cost(request, tokens_in, tokens_out, usage=usage),
                finish_reason=self._extract_responses_finish_reason(response_json),
            )

        choices = response_json.get("choices")
        first_choice = choices[0] if isinstance(choices, list) and choices else {}
        message = first_choice.get("message") if isinstance(first_choice, dict) else {}
        usage = response_json.get("usage", {})
        output_text = self._extract_message_content(message)
        output = {
            "output_text": output_text,
            "messages": [message] if isinstance(message, dict) else [],
            "model_id": response_json.get("model", request.model_id),
            "usage": usage if isinstance(usage, dict) else {},
        }
        tokens_in = self._coerce_int(usage.get("prompt_tokens"))
        tokens_out = self._coerce_int(usage.get("completion_tokens"))
        return ProviderExecutionResult(
            output=output,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=self._estimate_cost(request, tokens_in, tokens_out, usage=usage),
            finish_reason=(
                first_choice.get("finish_reason", "stop")
                if isinstance(first_choice, dict)
                else "stop"
            ),
        )

    def _build_image_media_candidates(
        self,
        response_json: dict[str, Any],
    ) -> tuple[ProviderMediaCandidate, ...]:
        raw_candidates = response_json.get("data")
        if not isinstance(raw_candidates, list):
            raw_candidates = response_json.get("images")
        if not isinstance(raw_candidates, list) or not raw_candidates:
            raise ProviderExecutionError(
                "provider.output_contract_invalid",
                "image generation response must contain a non-empty data or images list",
            )
        if len(raw_candidates) > MAX_PROVIDER_IMAGE_COUNT:
            raise ProviderExecutionError(
                "provider.output_contract_invalid",
                f"image generation response exceeds {MAX_PROVIDER_IMAGE_COUNT} candidates",
            )

        decoded_total = 0
        candidates: list[ProviderMediaCandidate] = []
        for index, raw_candidate in enumerate(raw_candidates, start=1):
            candidate_payload: dict[str, Any]
            if isinstance(raw_candidate, dict):
                candidate_payload = raw_candidate
            elif isinstance(raw_candidate, str):
                candidate_payload = {"url": raw_candidate}
            else:
                raise ProviderExecutionError(
                    "provider.output_contract_invalid",
                    f"image generation candidate {index} must be an object or URL string",
                )

            encoded_image = candidate_payload.get("b64_json")
            raw_source_url = candidate_payload.get("url")
            if encoded_image not in (None, "") and raw_source_url not in (None, ""):
                raise ProviderExecutionError(
                    "provider.output_contract_invalid",
                    f"image generation candidate {index} contains ambiguous media sources",
                )
            claimed_mime_type = self._optional_string(
                candidate_payload.get("mime_type") or candidate_payload.get("content_type")
            )
            revised_prompt = self._optional_string(candidate_payload.get("revised_prompt"))
            claimed_width = self._optional_positive_int(candidate_payload.get("width"))
            claimed_height = self._optional_positive_int(candidate_payload.get("height"))
            if encoded_image not in (None, ""):
                content_bytes = self._decode_provider_image_base64(encoded_image, index=index)
                decoded_total += len(content_bytes)
                if decoded_total > MAX_PROVIDER_IMAGE_TOTAL_BYTES:
                    raise ProviderExecutionError(
                        "provider.output_contract_invalid",
                        "image generation response exceeds the aggregate decoded byte limit",
                    )
                candidates.append(
                    ProviderMediaCandidate(
                        index=index,
                        content_bytes=content_bytes,
                        claimed_mime_type=claimed_mime_type,
                        revised_prompt=revised_prompt,
                        claimed_width=claimed_width,
                        claimed_height=claimed_height,
                    )
                )
                continue

            source_url = self._validate_provider_image_url(
                raw_source_url,
                index=index,
            )
            candidates.append(
                ProviderMediaCandidate(
                    index=index,
                    source_url=source_url,
                    image_output_hosts=self.image_output_hosts,
                    claimed_mime_type=claimed_mime_type,
                    revised_prompt=revised_prompt,
                    claimed_width=claimed_width,
                    claimed_height=claimed_height,
                )
            )

        return tuple(candidates)

    @staticmethod
    def _decode_provider_image_base64(value: object, *, index: int) -> bytes:
        if not isinstance(value, str) or not value:
            raise ProviderExecutionError(
                "provider.output_contract_invalid",
                f"image generation candidate {index} b64_json must be a non-empty string",
            )
        if len(value) > MAX_PROVIDER_IMAGE_BASE64_CHARS:
            raise ProviderExecutionError(
                "provider.output_contract_invalid",
                f"image generation candidate {index} exceeds the decoded byte limit",
            )
        try:
            content_bytes = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ProviderExecutionError(
                "provider.output_contract_invalid",
                f"image generation candidate {index} contains invalid Base64",
            ) from error
        if len(content_bytes) > MAX_PROVIDER_IMAGE_BYTES:
            raise ProviderExecutionError(
                "provider.output_contract_invalid",
                f"image generation candidate {index} exceeds the decoded byte limit",
            )
        return content_bytes

    @staticmethod
    def _validate_provider_image_url(value: object, *, index: int) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ProviderExecutionError(
                "provider.output_contract_invalid",
                f"image generation candidate {index} has no supported media source",
            )
        source_url = value.strip()
        try:
            parsed = urlsplit(source_url)
            parsed_port = parsed.port
        except ValueError as error:
            raise ProviderExecutionError(
                "provider.output_contract_invalid",
                f"image generation candidate {index} URL is invalid",
            ) from error
        if (
            parsed.scheme.lower() != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or (parsed_port is not None and parsed_port != 443)
        ):
            raise ProviderExecutionError(
                "provider.output_contract_invalid",
                f"image generation candidate {index} URL must be HTTPS",
            )
        return source_url

    @staticmethod
    def _optional_string(value: object) -> str:
        return value.strip() if isinstance(value, str) else ""

    @staticmethod
    def _optional_positive_int(value: object) -> int | None:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return None
        try:
            normalized = int(value)
        except (OverflowError, TypeError, ValueError):
            return None
        return normalized if normalized > 0 else None

    @staticmethod
    def _sanitize_image_generation_usage(value: object) -> dict[str, int | float]:
        if not isinstance(value, dict):
            return {}
        return {
            key: item
            for key, item in value.items()
            if key in ALLOWED_PROVIDER_IMAGE_USAGE_FIELDS
            and isinstance(item, (int, float))
            and not isinstance(item, bool)
            and (not isinstance(item, float) or math.isfinite(item))
        }

    @staticmethod
    def _normalize_image_output_hosts(value: Iterable[str]) -> tuple[str, ...]:
        normalized_hosts: list[str] = []
        for raw_host in value:
            host = str(raw_host or "").strip().rstrip(".").lower()
            if (
                not host
                or any(character.isspace() for character in host)
                or any(marker in host for marker in ("://", "/", "*", "@", "?", "#", ":"))
            ):
                raise ValueError("image_output_hosts must contain exact host names")
            try:
                host = host.encode("idna").decode("ascii")
            except UnicodeError as error:
                raise ValueError(
                    "image_output_hosts must contain valid exact host names"
                ) from error
            if host not in normalized_hosts:
                normalized_hosts.append(host)
        return tuple(normalized_hosts)

    def _execute_sample(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        source_text = self._collect_source_text(request.input_payload) or request.ability_name
        tokens_in = max(1, len(source_text.split()))
        latency_ms = 80 + (request.retry_count * 25)
        media_candidates: tuple[ProviderMediaCandidate, ...] = ()

        if request.execution_kind == "embedding":
            seed = sum(ord(character) for character in source_text)
            output = {
                "embedding": [
                    round(((seed + (index * 17)) % 1000) / 1000, 3) for index in range(4)
                ],
                "dimensions": 4,
                "model_id": request.model_id,
            }
            tokens_out = 0
            latency_ms += 10
        elif request.execution_kind == "image_generation":
            output = {
                "model_id": request.model_id,
                "candidate_count": 1,
            }
            media_candidates = (
                ProviderMediaCandidate(
                    index=1,
                    content_bytes=SAMPLE_IMAGE_PNG,
                    claimed_mime_type="image/png",
                    revised_prompt=source_text,
                    claimed_width=1,
                    claimed_height=1,
                ),
            )
            tokens_out = 0
            latency_ms += 120
        elif request.execution_kind == "vision":
            output_text = f"[hosted:{request.model_id}] vision summary for {source_text}"
            output = {
                "output_text": output_text,
                "messages": [{"role": "assistant", "content": output_text}],
                "model_id": request.model_id,
            }
            tokens_out = max(1, len(output_text.split()))
            latency_ms += 25
        else:
            output_text = f"[hosted:{request.model_id}] {source_text}"
            output = {
                "output_text": output_text,
                "messages": [{"role": "assistant", "content": output_text}],
                "model_id": request.model_id,
            }
            tokens_out = max(1, len(output_text.split()))

        if request.timeout_ms > 0 and latency_ms > request.timeout_ms:
            raise ProviderExecutionError(
                "provider.timeout",
                f"provider call exceeded timeout budget for {request.instance_id}",
            )

        return ProviderExecutionResult(
            output=output,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=self._estimate_cost(request, tokens_in, tokens_out),
            media_candidates=media_candidates,
        )

    def _resolve_request_options(self, payload: dict[str, Any]) -> dict[str, Any]:
        options: dict[str, Any] = {}
        nested_params = payload.get("params")
        if isinstance(nested_params, dict):
            options.update(nested_params)

        for key in (
            "messages",
            "input",
            "text",
            "encoding_format",
            "temperature",
            "max_tokens",
            "max_output_tokens",
            "top_p",
            "presence_penalty",
            "frequency_penalty",
            "response_format",
            "stop",
            "seed",
            "stream",
            "logit_bias",
            "stream_options",
            "metadata",
            "extra",
            "parallel_tool_calls",
            "max_completion_tokens",
            "n",
            "user",
            "tools",
            "tool_choice",
            "thinking",
            "prompt",
            "aspect_ratio",
            "resolution",
            "quality",
            "size",
        ):
            if key in payload and key not in options:
                options[key] = payload[key]

        return options

    def _apply_chat_request_options(
        self,
        payload: dict[str, Any],
        options: dict[str, Any],
    ) -> None:
        self._apply_common_request_options(payload, options)
        if isinstance(options.get("response_format"), dict):
            payload["response_format"] = options["response_format"]
        tools = self._normalize_chat_tools(options.get("tools"))
        if tools:
            payload["tools"] = tools
            tool_choice = self._normalize_chat_tool_choice(options.get("tool_choice"))
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice

    def _apply_responses_request_options(
        self,
        payload: dict[str, Any],
        options: dict[str, Any],
    ) -> None:
        self._apply_common_request_options(payload, options)
        response_format = self._normalize_responses_text_format(options.get("response_format"))
        if response_format is not None:
            payload["text"] = {"format": response_format}
        tools = self._normalize_responses_tools(options.get("tools"))
        if tools:
            payload["tools"] = tools
            tool_choice = self._normalize_responses_tool_choice(options.get("tool_choice"))
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice

    def _apply_common_request_options(
        self,
        payload: dict[str, Any],
        options: dict[str, Any],
    ) -> None:
        for numeric_key in ("top_p", "presence_penalty", "frequency_penalty"):
            if isinstance(options.get(numeric_key), (int, float)):
                payload[numeric_key] = options[numeric_key]
        if isinstance(options.get("stop"), str):
            payload["stop"] = options["stop"]
        elif isinstance(options.get("stop"), list):
            payload["stop"] = options["stop"]
        if isinstance(options.get("seed"), int):
            payload["seed"] = options["seed"]
        if isinstance(options.get("stream"), bool):
            payload["stream"] = options["stream"]
        if isinstance(options.get("logit_bias"), dict):
            payload["logit_bias"] = options["logit_bias"]
        if isinstance(options.get("stream_options"), dict):
            payload["stream_options"] = options["stream_options"]
        metadata = self._normalize_request_metadata(options.get("metadata"))
        if metadata:
            payload["metadata"] = metadata
        if isinstance(options.get("extra"), dict):
            for key, value in options["extra"].items():
                if isinstance(key, str) and key not in payload:
                    payload[key] = value
        if self.default_reasoning_effort and "reasoning_effort" not in payload:
            payload["reasoning_effort"] = self.default_reasoning_effort
        if "parallel_tool_calls" in options:
            payload["parallel_tool_calls"] = bool(options.get("parallel_tool_calls"))
        if isinstance(options.get("max_completion_tokens"), int):
            payload["max_completion_tokens"] = options["max_completion_tokens"]
        if isinstance(options.get("n"), int):
            payload["n"] = options["n"]
        if isinstance(options.get("user"), str) and options["user"].strip():
            payload["user"] = options["user"].strip()

        reasoning = self._normalize_reasoning(options.get("thinking"))
        if reasoning is not None:
            payload["reasoning"] = reasoning
        if reasoning is not None and isinstance(reasoning.get("max_reasoning_tokens"), int):
            payload["max_reasoning_tokens"] = reasoning["max_reasoning_tokens"]

    def _apply_image_generation_request_options(
        self,
        payload: dict[str, Any],
        options: dict[str, Any],
    ) -> None:
        if isinstance(options.get("n"), int):
            payload["n"] = max(1, min(MAX_PROVIDER_IMAGE_COUNT, int(options["n"])))
        for key in (
            "aspect_ratio",
            "resolution",
            "quality",
            "size",
            "user",
        ):
            value = options.get(key)
            if isinstance(value, str) and value.strip():
                payload[key] = value.strip()
        if self.image_response_format is not None:
            payload["response_format"] = self.image_response_format
        metadata = self._normalize_request_metadata(options.get("metadata"))
        if metadata:
            payload["metadata"] = metadata
        if isinstance(options.get("extra"), dict):
            for key, value in options["extra"].items():
                if isinstance(key, str) and key not in payload:
                    payload[key] = value

    @staticmethod
    def _normalize_request_metadata(value: object) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}

        normalized: dict[str, str] = {}
        for raw_key, raw_value in value.items():
            if len(normalized) >= MAX_REQUEST_METADATA_ENTRIES:
                break
            if not isinstance(raw_key, str):
                continue
            key = raw_key.strip()[:MAX_REQUEST_METADATA_KEY_CHARS]
            if not key:
                continue
            if isinstance(raw_value, bool):
                item = "true" if raw_value else "false"
            elif isinstance(raw_value, str):
                item = raw_value.strip()
            elif isinstance(raw_value, (int, float)):
                item = str(raw_value)
            else:
                continue
            if item:
                normalized[key] = item[:MAX_REQUEST_METADATA_VALUE_CHARS]
        return normalized

    def _resolve_image_generation_prompt(self, options: dict[str, Any]) -> str:
        prompt = options.get("prompt")
        if isinstance(prompt, str) and prompt.strip():
            return prompt.strip()
        text = options.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
        input_value = options.get("input")
        if isinstance(input_value, str) and input_value.strip():
            return input_value.strip()
        messages = options.get("messages")
        if isinstance(messages, list):
            collected: list[str] = []
            for message in messages:
                if not isinstance(message, dict):
                    continue
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    collected.append(content.strip())
            if collected:
                return "\n".join(collected)
        return ""

    def _normalize_reasoning(self, value: object) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        reasoning: dict[str, Any] = {}
        budget = value.get("budget")
        if isinstance(budget, str) and budget.strip():
            reasoning["effort"] = budget.strip()
        max_reasoning_tokens = value.get("max_reasoning_tokens")
        if isinstance(max_reasoning_tokens, int) and max_reasoning_tokens > 0:
            reasoning["max_reasoning_tokens"] = max_reasoning_tokens
        return reasoning or None

    def _normalize_chat_tools(self, value: object) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [tool for tool in value if isinstance(tool, dict)]

    def _normalize_chat_tool_choice(self, value: object) -> str | dict[str, Any] | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            return value
        return None

    def _normalize_responses_tools(self, value: object) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, Any]] = []
        for tool in value:
            if not isinstance(tool, dict):
                continue
            tool_type = str(tool.get("type") or "").strip()
            function_payload = tool.get("function")
            if tool_type == "function" and isinstance(function_payload, dict):
                normalized_tool = {
                    "type": "function",
                    "name": function_payload.get("name"),
                    "description": function_payload.get("description"),
                    "parameters": function_payload.get("parameters"),
                }
                if "strict" in function_payload:
                    normalized_tool["strict"] = function_payload.get("strict")
                normalized.append(
                    {
                        key: value
                        for key, value in normalized_tool.items()
                        if value is not None and value != ""
                    }
                )
                continue
            normalized.append(tool)
        return normalized

    def _normalize_responses_tool_choice(self, value: object) -> str | dict[str, Any] | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if not isinstance(value, dict):
            return None
        if str(value.get("type") or "").strip() != "function":
            return value
        function_payload = value.get("function")
        if isinstance(function_payload, dict):
            name = str(function_payload.get("name") or "").strip()
            if name:
                return {"type": "function", "name": name}
        name = str(value.get("name") or "").strip()
        if name:
            return {"type": "function", "name": name}
        return value

    def _normalize_responses_text_format(self, value: object) -> dict[str, Any] | None:
        if isinstance(value, dict) and value:
            return value
        if isinstance(value, str) and value.strip():
            return {"type": value.strip()}
        return None

    def _extract_responses_tool_calls(self, output: list[Any]) -> list[dict[str, Any]]:
        tool_calls: list[dict[str, Any]] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").strip()
            if item_type not in {"function_call", "custom_tool_call"}:
                continue
            tool_call = {
                "id": item.get("id") or item.get("call_id") or "",
                "type": "function",
                "function": {
                    "name": item.get("name") or "",
                    "arguments": item.get("arguments")
                    or item.get("input")
                    or item.get("arguments_json")
                    or "",
                },
            }
            tool_calls.append(tool_call)
        return tool_calls

    def _build_catalog_model_seed(
        self,
        payload: Any,
    ) -> CatalogModelSeed | None:
        if not isinstance(payload, dict):
            return None

        model_id = payload.get("id")
        if not isinstance(model_id, str) or not model_id:
            return None
        catalog_model_id = self._namespace_catalog_model_id(model_id)

        feature = self._infer_catalog_feature(model_id, payload)
        tier = self._infer_catalog_tier(model_id, feature, payload)
        region = self._infer_catalog_region(payload)
        status = self._infer_catalog_status(payload)
        is_deprecated = self._infer_catalog_deprecated(status, payload)
        endpoint_variant = self._select_catalog_endpoint_variant(feature, tier)

        return CatalogModelSeed(
            model_id=catalog_model_id,
            family=self._infer_catalog_family(model_id),
            feature=feature,
            status=status,
            context_window=self._coerce_int(
                self._lookup_nested(
                    payload,
                    ("context_window",),
                    ("context_length",),
                    ("max_context_tokens",),
                    ("metadata", "context_window"),
                    ("metadata", "context_length"),
                )
            ),
            price_input=self._coerce_float(
                self._lookup_nested(
                    payload,
                    ("price_input",),
                    ("pricing", "input"),
                    ("pricing", "input_per_million"),
                    ("metadata", "price_input"),
                )
            ),
            price_output=self._coerce_float(
                self._lookup_nested(
                    payload,
                    ("price_output",),
                    ("pricing", "output"),
                    ("pricing", "output_per_million"),
                    ("metadata", "price_output"),
                )
            ),
            is_deprecated=is_deprecated,
            fallback_candidate=(
                feature == "text"
                and tier in {"economy", "balanced"}
                and status == "available"
                and not is_deprecated
            ),
            raw_json={
                "catalog_source": "provider_api",
                "tier": tier,
                "owned_by": payload.get("owned_by"),
                "upstream_model_id": model_id,
            },
            instances=[
                CatalogInstanceSeed(
                    instance_id=(
                        f"{self._slugify(self.provider_id)}-"
                        f"{self._slugify(region)}-"
                        f"{self._slugify(catalog_model_id)}"
                    ),
                    endpoint_variant=endpoint_variant,
                    region=region,
                    capability_tags=self._build_catalog_capability_tags(
                        model_id,
                        feature,
                        tier,
                        payload,
                    ),
                    is_default=True,
                    weight=self._catalog_weight_for_tier(tier),
                )
            ],
        )

    def _catalog_sort_key(self, model_seed: CatalogModelSeed) -> tuple[int, int, str]:
        feature_rank = {"text": 0, "vision": 1, "image_generation": 2, "embedding": 3}.get(
            model_seed.feature,
            99,
        )
        tier = "default"
        if model_seed.raw_json:
            raw_tier = model_seed.raw_json.get("tier")
            if isinstance(raw_tier, str):
                tier = raw_tier
        tier_rank = {"economy": 0, "balanced": 1, "quality": 2, "default": 3}.get(
            tier,
            99,
        )
        return (feature_rank, tier_rank, model_seed.model_id)

    def _infer_catalog_feature(self, model_id: str, payload: dict[str, Any]) -> str:
        model_key = model_id.lower()
        explicit_feature = self._lookup_nested(
            payload,
            ("feature",),
            ("type",),
            ("metadata", "feature"),
        )
        if isinstance(explicit_feature, str):
            normalized_feature = explicit_feature.strip().lower()
            if normalized_feature in {"embedding", "text", "vision", "image_generation"}:
                return normalized_feature
            if normalized_feature in {"image", "images"}:
                return "image_generation"

        mode = self._lookup_nested(payload, ("mode",), ("metadata", "mode"))
        if isinstance(mode, str) and mode.strip().lower() in {
            "image",
            "image_generation",
        }:
            return "image_generation"

        image_generation_keywords = (
            "grok-imagine",
            "image-quality",
            "gpt-image",
            "qwen-image",
            "z-image",
            "ernie-image",
            "image-generation",
        )
        if any(keyword in model_key for keyword in image_generation_keywords):
            return "image_generation"

        output_modalities = set(self._collect_catalog_output_modalities(payload))
        if "image" in output_modalities:
            return "image_generation"

        capability_values = set(self._collect_catalog_capability_values(payload))
        if capability_values.intersection({"embedding", "embeddings"}):
            return "embedding"
        if "image_generation" in capability_values:
            return "image_generation"

        if "embedding" in model_key or self._looks_like_embedding_model(model_key):
            return "embedding"

        modalities = set(self._collect_catalog_modalities(payload))
        if "image" in modalities or "vision" in modalities:
            return "vision"

        if any(keyword in model_key for keyword in ("vision", "multimodal", "omni")):
            return "vision"

        return "text"

    def _looks_like_embedding_model(self, model_key: str) -> bool:
        tokens = [token for token in re.split(r"[^a-z0-9]+", model_key) if token]
        return "bge" in tokens

    def _infer_catalog_tier(
        self,
        model_id: str,
        feature: str,
        payload: dict[str, Any],
    ) -> str:
        explicit_tier = self._lookup_nested(
            payload,
            ("tier",),
            ("metadata", "tier"),
            ("raw", "tier"),
        )
        if isinstance(explicit_tier, str):
            normalized_tier = explicit_tier.strip().lower()
            if normalized_tier in {"economy", "balanced", "quality", "default"}:
                return normalized_tier

        if feature == "embedding":
            return "default"
        if feature in {"vision", "image_generation"}:
            return "quality"

        model_key = model_id.lower()
        economy_keywords = ("nano", "small", "haiku", "flash-lite", "chat")
        balanced_keywords = ("mini", "medium", "flash", "turbo", "v3")
        quality_keywords = (
            "gpt-5",
            "gpt-4.5",
            "gpt-4.1",
            "gpt-4o",
            "o1",
            "o3",
            "opus",
            "sonnet",
            "pro",
            "large",
            "r1",
            "reasoner",
        )

        if any(keyword in model_key for keyword in economy_keywords):
            return "economy"
        if any(keyword in model_key for keyword in balanced_keywords):
            return "balanced"
        if any(keyword in model_key for keyword in quality_keywords):
            return "quality"
        return "balanced"

    def _infer_catalog_family(self, model_id: str) -> str:
        normalized = model_id.strip().lower()
        if not normalized:
            return model_id

        parts = [part for part in re.split(r"[-_]", normalized) if part]
        if "embedding" in parts:
            embedding_index = parts.index("embedding")
            family_parts = parts[: min(len(parts), embedding_index + 2)]
            if len(family_parts) >= 2:
                return "-".join(family_parts)
        if len(parts) >= 2 and any(character.isdigit() for character in parts[1]):
            return "-".join(parts[:2])
        if parts:
            return parts[0]
        return model_id

    def _namespace_catalog_model_id(self, model_id: str) -> str:
        normalized = str(model_id or "").strip()
        if not normalized or not self.model_namespace_prefix:
            return normalized
        prefix = f"{self.model_namespace_prefix}/"
        if normalized.lower().startswith(prefix.lower()):
            return normalized
        return f"{self.model_namespace_prefix}/{normalized}"

    def _resolve_runtime_model_id(self, model_id: str) -> str:
        normalized = str(model_id or "").strip()
        if not normalized or not self.model_namespace_prefix:
            return normalized
        prefix = f"{self.model_namespace_prefix}/"
        if normalized.lower().startswith(prefix.lower()):
            return normalized[len(prefix) :]
        return normalized

    def _infer_catalog_region(self, payload: dict[str, Any]) -> str:
        region = self._lookup_nested(
            payload,
            ("region",),
            ("metadata", "region"),
            ("deployment", "region"),
        )
        if isinstance(region, str) and region.strip():
            return self._slugify(region)
        return "global"

    def _infer_catalog_status(self, payload: dict[str, Any]) -> str:
        status = self._lookup_nested(
            payload,
            ("status",),
            ("metadata", "status"),
        )
        if isinstance(status, str) and status.strip():
            normalized = status.strip().lower()
            if normalized in {"available", "unavailable", "deprecated"}:
                return "deprecated" if normalized == "deprecated" else normalized

        if payload.get("archived") is True:
            return "unavailable"
        return "available"

    def _infer_catalog_deprecated(
        self,
        status: str,
        payload: dict[str, Any],
    ) -> bool:
        if status == "deprecated":
            return True
        deprecated = self._lookup_nested(
            payload,
            ("deprecated",),
            ("metadata", "deprecated"),
        )
        return deprecated is True

    def _select_catalog_endpoint_variant(self, feature: str, tier: str) -> str:
        if feature == "embedding":
            return "embeddings"
        if feature == "image_generation":
            return "image_generations"
        if feature == "vision" or tier == "quality":
            return "responses"
        return "chat_completions"

    def _build_catalog_capability_tags(
        self,
        model_id: str,
        feature: str,
        tier: str,
        payload: dict[str, Any],
    ) -> list[str]:
        tags: list[str] = [feature]
        if feature == "embedding":
            tags.append("default")
        elif feature == "image_generation":
            tags.extend(["default", "quality"])
        elif feature == "vision":
            tags.extend(["default", "quality"])
        else:
            tags.append(tier)

        explicit_tags = self._lookup_nested(
            payload,
            ("capability_tags",),
            ("metadata", "capability_tags"),
        )
        if isinstance(explicit_tags, list):
            for tag in explicit_tags:
                if isinstance(tag, str) and tag and tag not in tags:
                    tags.append(tag)

        model_key = str(model_id or "").strip().lower()
        commercial_tier = self._lookup_nested(
            payload,
            ("commercial_tier",),
            ("metadata", "commercial_tier"),
            ("billing", "tier"),
        )
        if model_key in {"gpt-5.5", "openai/gpt-5.5"} or (
            model_key.startswith("gpt-5.5")
            and isinstance(commercial_tier, str)
            and commercial_tier.strip().lower() == "free"
        ):
            for tag in ("free-gpt55", "hosted-free"):
                if tag not in tags:
                    tags.append(tag)

        return tags

    def _collect_catalog_output_modalities(self, payload: dict[str, Any]) -> list[str]:
        values: list[str] = []
        raw = payload.get("output_modalities")
        if isinstance(raw, list):
            values.extend(str(item).strip().lower() for item in raw if str(item).strip())
        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            raw = metadata.get("output_modalities")
            if isinstance(raw, list):
                values.extend(str(item).strip().lower() for item in raw if str(item).strip())
        return values

    def _collect_catalog_capability_values(self, payload: dict[str, Any]) -> list[str]:
        values: list[str] = []
        for raw in (
            payload.get("capabilities"),
            payload.get("capability_tags"),
            self._lookup_nested(payload, ("metadata", "capabilities")),
            self._lookup_nested(payload, ("metadata", "capability_tags")),
        ):
            if isinstance(raw, list):
                values.extend(str(item).strip().lower() for item in raw if str(item).strip())
        return values

    def _catalog_weight_for_tier(self, tier: str) -> int:
        return {
            "economy": 80,
            "balanced": 100,
            "quality": 120,
            "default": 100,
        }.get(tier, 100)

    def _extract_image_generation_cost(self, usage: Any) -> float:
        if not isinstance(usage, dict):
            return 0.0
        for key in ("cost_in_usd", "cost_usd", "cost"):
            value = self._coerce_float(usage.get(key))
            if value is not None and value > 0:
                return round(value, 6)
        ticks = self._coerce_float(usage.get("cost_in_usd_ticks"))
        if ticks is not None and ticks > 0:
            return round(ticks / 100_000_000, 6)
        return 0.0

    def _estimate_cost(
        self,
        request: ProviderExecutionRequest,
        tokens_in: int,
        tokens_out: int,
        *,
        usage: dict[str, Any] | None = None,
    ) -> float:
        deepseek_cost = self._estimate_deepseek_cost(
            request=request,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            usage=usage or {},
        )
        if deepseek_cost is not None:
            return deepseek_cost

        if request.price_input is None and request.price_output is None:
            return 0.0

        input_cost = ((request.price_input or 0.0) * tokens_in) / 1_000_000
        output_cost = ((request.price_output or 0.0) * tokens_out) / 1_000_000
        return round(input_cost + output_cost, 6)

    def _estimate_deepseek_cost(
        self,
        *,
        request: ProviderExecutionRequest,
        tokens_in: int,
        tokens_out: int,
        usage: dict[str, Any],
    ) -> float | None:
        pricing = DEEPSEEK_MODEL_PRICING_PER_MILLION.get(
            self._normalize_deepseek_model_id(request.model_id)
        )
        if pricing is None:
            return None

        cache_hit_tokens = self._coerce_int(
            usage.get("prompt_cache_hit_tokens")
            or usage.get("cache_hit_tokens")
            or usage.get("input_cache_hit_tokens")
        )
        cache_miss_tokens = self._coerce_int(
            usage.get("prompt_cache_miss_tokens")
            or usage.get("cache_miss_tokens")
            or usage.get("input_cache_miss_tokens")
        )
        if cache_hit_tokens == 0 and cache_miss_tokens == 0:
            cache_miss_tokens = max(0, int(tokens_in or 0))

        input_hit_cost = (pricing["input_cache_hit"] * max(0, cache_hit_tokens)) / 1_000_000
        input_miss_cost = (pricing["input_cache_miss"] * max(0, cache_miss_tokens)) / 1_000_000
        output_cost = (pricing["output"] * max(0, int(tokens_out or 0))) / 1_000_000
        return round(input_hit_cost + input_miss_cost + output_cost, 6)

    def _normalize_deepseek_model_id(self, model_id: str) -> str:
        normalized = str(model_id or "").strip().lower()
        if "/" in normalized:
            normalized = normalized.rsplit("/", 1)[-1]
        if ":" in normalized:
            normalized = normalized.rsplit(":", 1)[-1]
        if normalized.startswith("deepseek-v4-flash"):
            return "deepseek-v4-flash"
        if normalized.startswith("deepseek-v4-pro"):
            return "deepseek-v4-pro"
        return normalized

    def _maybe_raise_simulated_error(self, request: ProviderExecutionRequest) -> None:
        input_payload = request.input_payload
        if input_payload.get("simulate_timeout") is True:
            raise ProviderExecutionError(
                "provider.timeout",
                f"simulated timeout for {request.instance_id}",
            )

        fail_instances = input_payload.get("simulate_error_for_instances", [])
        if isinstance(fail_instances, list) and request.instance_id in fail_instances:
            raise ProviderExecutionError(
                "provider.simulated_error",
                f"simulated provider failure for {request.instance_id}",
            )

        fail_models = input_payload.get("simulate_error_for_models", [])
        if isinstance(fail_models, list) and request.model_id in fail_models:
            raise ProviderExecutionError(
                "provider.simulated_error",
                f"simulated provider failure for {request.model_id}",
            )

    def _resolve_chat_messages(
        self,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        messages = payload.get("messages")
        if isinstance(messages, list):
            normalized = [message for message in messages if isinstance(message, dict)]
            if normalized:
                return normalized

        source_text = self._collect_source_text(payload)
        return [{"role": "user", "content": source_text or "empty input"}]

    def _resolve_responses_input(self, payload: dict[str, Any]) -> Any:
        if "input" in payload:
            return payload["input"]

        messages = payload.get("messages")
        if isinstance(messages, list) and messages:
            return messages

        source_text = self._collect_source_text(payload)
        return source_text or payload

    def _resolve_embedding_input(self, payload: dict[str, Any]) -> Any:
        if "input" in payload:
            return payload["input"]

        source_text = self._collect_source_text(payload)
        return source_text or payload

    def _extract_message_content(self, message: Any) -> str:
        if not isinstance(message, dict):
            return ""

        content = message.get("content")
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            fragments: list[str] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if isinstance(block.get("text"), str):
                    fragments.append(block["text"])
                    continue
                if isinstance(block.get("content"), str):
                    fragments.append(block["content"])

            return " ".join(fragment for fragment in fragments if fragment).strip()

        return ""

    def _extract_responses_output_text(self, payload: dict[str, Any]) -> str:
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text:
            return output_text

        output = payload.get("output")
        if not isinstance(output, list):
            return ""

        fragments: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if isinstance(block.get("text"), str):
                    fragments.append(block["text"])
                    continue
                if isinstance(block.get("content"), str):
                    fragments.append(block["content"])

        return " ".join(fragment for fragment in fragments if fragment).strip()

    def _extract_responses_finish_reason(self, payload: dict[str, Any]) -> str:
        output = payload.get("output")
        if isinstance(output, list):
            for item in output:
                if isinstance(item, dict) and isinstance(item.get("status"), str):
                    if item["status"] == "completed":
                        return "stop"

        return "stop"

    def _map_http_status_error(self, status_code: int) -> str:
        if status_code == 401:
            return "provider.auth_invalid"
        if status_code == 403:
            return "provider.access_denied"
        if status_code == 404:
            return "provider.endpoint_not_found"
        if status_code == 408:
            return "provider.timeout"
        if status_code == 422:
            return "provider.invalid_request"
        if status_code == 429:
            return "provider.rate_limited"
        if status_code in {502, 503, 504}:
            return "provider.upstream_unavailable"
        if status_code >= 500:
            return "provider.upstream_error"
        return "provider.invalid_request"

    def _extract_http_error_message(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return self._bounded_response_text(response) or f"http {response.status_code}"

        error = payload.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return self._bounded_error_message(error["message"])

        if isinstance(payload.get("message"), str):
            return self._bounded_error_message(payload["message"])

        return self._bounded_response_text(response) or f"http {response.status_code}"

    def _bounded_response_text(self, response: httpx.Response) -> str:
        return self._bounded_error_message(response.text)

    def _bounded_error_message(self, message: str) -> str:
        return _truncate_upstream_error_message(message)

    def _collect_catalog_modalities(self, payload: dict[str, Any]) -> list[str]:
        values: list[str] = []
        for key in ("modalities", "input_modalities", "output_modalities"):
            raw_value = payload.get(key)
            if isinstance(raw_value, list):
                values.extend(
                    value.strip().lower()
                    for value in raw_value
                    if isinstance(value, str) and value.strip()
                )

        metadata_modalities = self._lookup_nested(payload, ("metadata", "modalities"))
        if isinstance(metadata_modalities, list):
            values.extend(
                value.strip().lower()
                for value in metadata_modalities
                if isinstance(value, str) and value.strip()
            )

        return values

    def _lookup_nested(
        self,
        payload: dict[str, Any],
        *paths: tuple[str, ...],
    ) -> Any:
        for path in paths:
            current: Any = payload
            found = True
            for segment in path:
                if not isinstance(current, dict) or segment not in current:
                    found = False
                    break
                current = current[segment]
            if found:
                return current
        return None

    def _slugify(self, value: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
        normalized = normalized.strip("-")
        return normalized or "default"

    def _coerce_float(self, value: Any) -> float | None:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            try:
                normalized = float(value)
            except (OverflowError, ValueError):
                return None
            return normalized if math.isfinite(normalized) else None
        if isinstance(value, str):
            try:
                normalized = float(value)
            except (OverflowError, ValueError):
                return None
            return normalized if math.isfinite(normalized) else None
        return None

    def _collect_source_text(self, payload: dict[str, Any]) -> str:
        messages = payload.get("messages")
        if isinstance(messages, list):
            fragments: list[str] = []
            for message in messages:
                if not isinstance(message, dict):
                    continue

                content = message.get("content")
                if isinstance(content, str):
                    fragments.append(content)
                    continue

                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and isinstance(block.get("text"), str):
                            fragments.append(block["text"])

            if fragments:
                return " ".join(fragments).strip()

        if isinstance(payload.get("input_text"), str):
            return payload["input_text"]
        if isinstance(payload.get("text"), str):
            return payload["text"]

        return ""

    def _coerce_int(self, value: object | None) -> int:
        if isinstance(value, bool):
            return 0
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                return 0
            return int(value)
        return 0
